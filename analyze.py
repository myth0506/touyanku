#!/usr/bin/env python3
"""
财报分析主控脚本。

用法：
    python analyze.py /path/to/report.pdf [--api-key sk-xxx]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# 将脚本所在目录加入路径，以便导入 parse_report
SCRIPT_DIR = Path(__file__).parent.resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import parse_report


# --------------------------- 路径常量 ---------------------------
TEMPLATE_DIR = SCRIPT_DIR / "模版"
REPORT_TEMPLATE = TEMPLATE_DIR / "财报分析模板.md"
HOMEPAGE_TEMPLATE = TEMPLATE_DIR / "公司主页模板.md"
COMPANY_HOME_DIR = SCRIPT_DIR / "公司主页"
ANALYSIS_DIR = SCRIPT_DIR / "财报分析"


# --------------------------- 辅助函数 ---------------------------
def ensure_dirs():
    """确保必要目录存在。"""
    COMPANY_HOME_DIR.mkdir(parents=True, exist_ok=True)
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


def read_template(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"模板文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def fmt(val, unit="", default="N/A"):
    """格式化数值，None 时返回 default。"""
    if val is None:
        return default
    if isinstance(val, float):
        # 去掉无意义的小数尾零
        s = f"{val:.4f}".rstrip("0").rstrip(".")
        return s + unit
    return str(val) + unit


def parse_period_info(report_period: str | None) -> tuple[str, str]:
    """从报告期解析年份和报告类型。"""
    if not report_period:
        return "未知", "未知报告"

    year_match = re.search(r"(\d{4})", report_period)
    year = year_match.group(1) if year_match else "未知"

    if "年度" in report_period:
        report_type = "年度报告"
    elif "半年度" in report_period:
        report_type = "半年度报告"
    elif "第一季度" in report_period or "一季度" in report_period:
        report_type = "第一季度报告"
    elif "第二季度" in report_period or "二季度" in report_period:
        report_type = "第二季度报告"
    elif "第三季度" in report_period or "三季度" in report_period:
        report_type = "第三季度报告"
    elif "第四季度" in report_period or "四季度" in report_period:
        report_type = "第四季度报告"
    else:
        report_type = report_period

    return year, report_type


def build_analysis_note(data: dict) -> tuple[str, Path]:
    """
    填充财报分析模板，返回 (markdown_content, target_path)。
    """
    template = read_template(REPORT_TEMPLATE)
    today = datetime.now().strftime("%Y-%m-%d")

    company_name = data.get("company_name") or "未知公司"
    stock_code = data.get("stock_code") or "未知代码"
    report_period = data.get("report_period") or "未知报告期"
    year, report_type = parse_period_info(report_period)

    # 营收
    revenue = data.get("revenue") or {}
    # 净利润
    net_profit = data.get("net_profit_attributable") or {}
    # 研发
    rd = data.get("rd_expense") or {}
    # 现金流
    cashflow = data.get("operating_cash_flow") or {}
    # AI 洞察
    ai = data.get("ai_insights") or {}

    def bullet_list(items):
        if not items:
            return "- 无数据"
        return "\n".join(f"- {item}" for item in items)

    mapping = {
        "company_name": company_name,
        "stock_code": stock_code,
        "report_period": report_period,
        "report_type": report_type,
        "analysis_date": today,
        "revenue_current": fmt(revenue.get("current")),
        "revenue_previous": fmt(revenue.get("previous")),
        "revenue_yoy": fmt(revenue.get("yoy_change"), "%"),
        "net_profit_current": fmt(net_profit.get("current")),
        "net_profit_previous": fmt(net_profit.get("previous")),
        "net_profit_yoy": fmt(net_profit.get("yoy_change"), "%"),
        "gross_margin_pct": fmt(data.get("gross_margin_pct")),
        "net_margin_pct": fmt(data.get("net_margin_pct")),
        "roe_weighted_avg_pct": fmt(data.get("roe_weighted_avg_pct")),
        "basic_eps": fmt(data.get("basic_eps")),
        "rd_expense_current": fmt(rd.get("current")),
        "rd_expense_yoy": fmt(rd.get("yoy_change"), "%"),
        "rd_revenue_ratio_pct": fmt(data.get("rd_revenue_ratio_pct")),
        "operating_cash_flow_current": fmt(cashflow.get("current")),
        "debt_to_asset_ratio_pct": fmt(data.get("debt_to_asset_ratio_pct")),
        "core_strategies": bullet_list(ai.get("core_strategies")),
        "major_risks": bullet_list(ai.get("major_risks")),
        "key_changes": bullet_list(ai.get("key_changes")),
    }

    for key, val in mapping.items():
        template = template.replace(f"{{{{{key}}}}}", str(val))

    # 目标路径: ./财报分析/年份/公司名称_报告期.md
    year_dir = ANALYSIS_DIR / year
    year_dir.mkdir(parents=True, exist_ok=True)
    safe_company = company_name.replace("/", "-").replace("\\", "-")
    filename = f"{safe_company}_{report_period}.md"
    target_path = year_dir / filename

    return template, target_path


def build_homepage(data: dict, report_path: Path) -> tuple[str, Path, bool]:
    """
    返回 (content, homepage_path, is_new)。
    is_new 为 True 表示本次新建了主页。
    """
    company_name = data.get("company_name") or "未知公司"
    stock_code = data.get("stock_code") or "未知代码"
    report_period = data.get("report_period") or "未知报告期"
    today = datetime.now().strftime("%Y-%m-%d")

    safe_company = company_name.replace("/", "-").replace("\\", "-")
    homepage_path = COMPANY_HOME_DIR / f"{safe_company}.md"

    # 笔记链接（wiki-link 格式）
    # 相对路径从公司主页到财报分析笔记
    rel_link = os.path.relpath(report_path, homepage_path.parent)
    link_line = f"- [[{rel_link}|{report_period}]]"

    if homepage_path.exists():
        content = homepage_path.read_text(encoding="utf-8")
        is_new = False

        # 在 "## 财报记录" 章节下追加链接
        if "## 财报记录" in content:
            # 找到 "## 财报记录" 之后、下一个 ## 之前的位置插入
            lines = content.splitlines()
            insert_idx = len(lines)
            found = False
            for i, line in enumerate(lines):
                if line.strip().startswith("## 财报记录"):
                    found = True
                    insert_idx = i + 1
                elif found and line.strip().startswith("## "):
                    insert_idx = i
                    break
            # 避免重复追加
            if link_line not in content:
                lines.insert(insert_idx, link_line)
                content = "\n".join(lines)
        else:
            # 没有财报记录章节，直接追加到末尾
            if link_line not in content:
                content = content.rstrip() + "\n\n## 财报记录\n\n" + link_line + "\n"
    else:
        template = read_template(HOMEPAGE_TEMPLATE)
        mapping = {
            "company_name": company_name,
            "stock_code": stock_code,
            "created_date": today,
            "financial_reports": link_line,
        }
        for key, val in mapping.items():
            template = template.replace(f"{{{{{key}}}}}", str(val))
        content = template
        is_new = True

    return content, homepage_path, is_new


def run(pdf_path: str, api_key: str | None = None):
    ensure_dirs()

    print(f"📄 正在解析: {pdf_path}")
    data = parse_report.parse_report(pdf_path, api_key=api_key)

    # 生成财报分析笔记
    note_content, note_path = build_analysis_note(data)
    note_path.write_text(note_content, encoding="utf-8")
    print(f"📝 财报笔记已生成: {note_path}")

    # 处理公司主页
    homepage_content, homepage_path, is_new = build_homepage(data, note_path)
    homepage_path.write_text(homepage_content, encoding="utf-8")
    if is_new:
        print(f"🏠 新建公司主页: {homepage_path}")
    else:
        print(f"🏠 更新公司主页: {homepage_path}")

    # 输出摘要
    company_name = data.get("company_name") or "未知公司"
    stock_code = data.get("stock_code") or "未知代码"
    report_period = data.get("report_period") or "未知报告期"

    print("\n" + "=" * 50)
    print("处理结果摘要")
    print("=" * 50)
    print(f"输入文件      : {pdf_path}")
    print(f"公司          : {company_name} ({stock_code})")
    print(f"报告期        : {report_period}")
    print(f"财报笔记      : {note_path}")
    print(f"公司主页      : {homepage_path} ({'新建' if is_new else '追加链接'})")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="财报分析主控脚本")
    parser.add_argument("pdf_path", help="财报 PDF 文件路径")
    parser.add_argument("--api-key", default=None, help="Anthropic API Key（默认读取 ANTHROPIC_API_KEY 环境变量）")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("⚠️  警告: 未提供 Anthropic API Key，AI 语义分析可能失败。")
        print("     可通过 --api-key 参数或 ANTHROPIC_API_KEY 环境变量设置。")

    run(args.pdf_path, api_key=api_key)


if __name__ == "__main__":
    main()
