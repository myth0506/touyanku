import argparse
import json
import re
import sys
from pathlib import Path

import fitz  # pymupdf
from anthropic import Anthropic


def extract_text_from_pdf(pdf_path: str) -> str:
    """提取 PDF 全部文本内容。"""
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def extract_company_info(text: str) -> dict:
    """提取公司全称、股票代码、报告期。"""
    info = {"company_name": None, "stock_code": None, "report_period": None}

    # 股票代码：6位数字，通常在标题附近
    code_match = re.search(r"(\d{6})", text[:5000])
    if code_match:
        info["stock_code"] = code_match.group(1)

    # 公司全称
    name_patterns = [
        r"([一-龥]{2,20}股份有限公司)",
        r"公司全称[：:]\s*([一-龥]{2,30}(?:有限公司|股份有限公司))",
    ]
    for pat in name_patterns:
        m = re.search(pat, text[:10000])
        if m:
            info["company_name"] = m.group(1)
            break

    # 报告期
    period_patterns = [
        r"(\d{4}\s*年\s*年度\s*报告)",
        r"(\d{4}\s*年\s*半年度\s*报告)",
        r"(\d{4}\s*年\s*第[一二三四]季度\s*报告)",
        r"(\d{4}\s*年度)",
    ]
    for pat in period_patterns:
        m = re.search(pat, text[:5000])
        if m:
            info["report_period"] = m.group(1).replace(" ", "")
            break

    return info


def extract_financial_value(text: str, keywords: list, unit_multiplier: float = 1.0) -> dict:
    """根据关键词列表在文本中查找财务数值（当期、上期、同比）。"""
    result = {"current": None, "previous": None, "yoy_change": None}

    for keyword in keywords:
        # 尽量匹配表格行：关键词 + 数字 + 数字 + 百分比
        pattern = (
            rf"{keyword}[\s\w]*?"
            rf"([\-]?\d{{1,3}}(?:,\d{{3}})*(?:\.\d+)?)"  # 当期
            rf"[\s\w]*?"
            rf"([\-]?\d{{1,3}}(?:,\d{{3}})*(?:\.\d+)?)"  # 上期
            rf"[\s\w]*?"
            rf"([\-]?\d{{1,3}}(?:,\d{{3}})*(?:\.\d+)?)\s*%"  # 同比
        )
        m = re.search(pattern, text, re.DOTALL)
        if m:
            result["current"] = float(m.group(1).replace(",", "")) * unit_multiplier
            result["previous"] = float(m.group(2).replace(",", "")) * unit_multiplier
            result["yoy_change"] = float(m.group(3).replace(",", ""))
            break

    if result["current"] is None:
        # 降级：只找第一个出现的数字
        for keyword in keywords:
            m = re.search(rf"{keyword}.*?([\-]?\d{{1,3}}(?:,\d{{3}})*(?:\.\d+)?)", text, re.DOTALL)
            if m:
                result["current"] = float(m.group(1).replace(",", "")) * unit_multiplier
                break

    return result


def extract_single_value(text: str, keywords: list, unit_multiplier: float = 1.0, suffix: str = "") -> float | None:
    """提取单个数值。"""
    for keyword in keywords:
        pat = rf"{keyword}.*?([\-]?\d{{1,3}}(?:,\d{{3}})*(?:\.\d+)?)\s*{suffix}"
        m = re.search(pat, text, re.DOTALL)
        if m:
            return float(m.group(1).replace(",", "")) * unit_multiplier
    return None


def extract_financial_data(text: str) -> dict:
    """提取全部结构化财务数据。"""
    data = {}

    # 营业收入
    revenue = extract_financial_value(
        text,
        ["营业收入", "营业总收入", "主营业务收入"],
        unit_multiplier=1e8,  # 默认亿元
    )
    data["revenue"] = revenue

    # 归母净利润
    net_profit = extract_financial_value(
        text,
        ["归属于上市公司股东的净利润", "归母净利润", "净利润"],
        unit_multiplier=1e8,
    )
    data["net_profit_attributable"] = net_profit

    # 毛利率
    gross_margin = extract_single_value(text, ["毛利率"], suffix="%")
    if gross_margin is None and revenue["current"] and revenue["current"] > 0:
        # 尝试通过营业成本计算
        cost = extract_single_value(text, ["营业成本"], unit_multiplier=1e8)
        if cost:
            gross_margin = round((revenue["current"] - cost) / revenue["current"] * 100, 2)
    data["gross_margin_pct"] = gross_margin

    # 净利率
    net_margin = extract_single_value(text, ["净利率", "销售净利率"], suffix="%")
    if net_margin is None and revenue["current"] and net_profit["current"] and revenue["current"] > 0:
        net_margin = round(net_profit["current"] / revenue["current"] * 100, 2)
    data["net_margin_pct"] = net_margin

    # 研发费用
    rd = extract_financial_value(
        text,
        ["研发费用", "研发支出"],
        unit_multiplier=1e8,
    )
    data["rd_expense"] = rd
    if rd["current"] and revenue["current"] and revenue["current"] > 0:
        data["rd_revenue_ratio_pct"] = round(rd["current"] / revenue["current"] * 100, 2)
    else:
        data["rd_revenue_ratio_pct"] = None

    # 经营活动现金流净额
    cashflow = extract_financial_value(
        text,
        ["经营活动产生的现金流量净额", "经营活动现金流净额"],
        unit_multiplier=1e8,
    )
    data["operating_cash_flow"] = cashflow

    # 资产负债率
    debt_ratio = extract_single_value(text, ["资产负债率"], suffix="%")
    data["debt_to_asset_ratio_pct"] = debt_ratio

    # ROE
    roe = extract_single_value(text, ["加权平均净资产收益率", "净资产收益率"], suffix="%")
    data["roe_weighted_avg_pct"] = roe

    # 基本每股收益
    eps = extract_single_value(text, ["基本每股收益"])
    data["basic_eps"] = eps

    return data


def ai_extract_insights(text: str, api_key: str | None = None) -> dict:
    """调用 Anthropic API 提取语义信息。"""
    client = Anthropic(api_key=api_key)

    # 截取前 150K 字符左右，避免超出上下文
    truncated = text[:120000]

    prompt = f"""
你是一位专业的财务分析师。请基于以下财报文本，提取以下信息并以 JSON 格式返回（不要包含任何 markdown 代码块标记，只返回纯 JSON）：

1. "core_strategies": 董事长致辞或管理层讨论与分析中提到的 3 个核心战略重点（列表）
2. "major_risks": 风险因素章节中披露的 3 个主要风险（列表）
3. "key_changes": 本期相比上期，经营层面最值得关注的 1-2 个变化（列表）

财报文本：
{truncated}

要求：
- 只返回合法的 JSON，不要任何解释文字
- JSON 格式：{{"core_strategies": [...], "major_risks": [...], "key_changes": [...]}}
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.content[0].text.strip()
        # 去除可能的代码块
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE)
        return json.loads(content)
    except Exception as e:
        return {
            "core_strategies": [],
            "major_risks": [],
            "key_changes": [],
            "error": str(e),
        }


def parse_report(pdf_path: str, api_key: str | None = None) -> dict:
    """主入口：解析财报 PDF，返回结构化字典。"""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

    text = extract_text_from_pdf(pdf_path)

    result = {}
    result.update(extract_company_info(text))
    result.update(extract_financial_data(text))
    result["ai_insights"] = ai_extract_insights(text, api_key=api_key)

    return result


def main():
    parser = argparse.ArgumentParser(description="解析财报 PDF 并提取关键财务数据与 AI 洞察")
    parser.add_argument("pdf_path", help="财报 PDF 文件路径")
    parser.add_argument("--api-key", default=None, help="Anthropic API Key（默认读取 ANTHROPIC_API_KEY 环境变量）")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径（默认打印到 stdout）")
    args = parser.parse_args()

    api_key = args.api_key or None  # Anthropic 客户端会自动读环境变量
    result = parse_report(args.pdf_path, api_key=api_key)

    json_str = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(json_str, encoding="utf-8")
        print(f"结果已保存至: {args.output}")
    else:
        print(json_str)


if __name__ == "__main__":
    main()
