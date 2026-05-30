#!/usr/bin/env python3
"""
Batch 财报分析调度脚本
调用 Claude CLI 以非交互模式 (-p) 逐个处理季度财报数据包。
"""

import os
import re
import sys
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path("/Users/xiekai/Documents/投研库")
RAW_DATA_DIR = BASE_DIR / "原始数据"
ANALYSIS_DIR = BASE_DIR / "财报分析"
TODO_DIR = BASE_DIR / "待办"

# ============================================================
# 工具函数
# ============================================================

def parse_quarter(dirname: str) -> Tuple[int, int, str]:
    """
    从目录名解析财年、季度，并返回排序键。
    支持格式：FY2015-Q2-Asset-Package, FY26q2-zip, FY2026-Q3-Asset-Package
    """
    # 尝试匹配 FYYYYY-QX 或 FYyyqx 格式
    m = re.search(r'FY(\d{4})-Q(\d)', dirname, re.IGNORECASE)
    if m:
        year = int(m.group(1))
        quarter = int(m.group(2))
        return (year, quarter, dirname)

    m = re.search(r'FY(\d{2})q(\d)', dirname, re.IGNORECASE)
    if m:
        year = int("20" + m.group(1))
        quarter = int(m.group(2))
        return (year, quarter, dirname)

    # 无法解析的排最后
    return (9999, 99, dirname)


def get_existing_notes(company: str) -> set:
    """扫描已有的分析笔记，返回已处理的季度目录名集合（近似匹配）。"""
    company_analysis_dir = ANALYSIS_DIR / company
    if not company_analysis_dir.exists():
        return set()

    existing = set()
    for f in company_analysis_dir.iterdir():
        if f.is_file() and f.suffix == ".md":
            # 从文件名推断季度，例如 MSFT_FY16Q2.md -> FY2016-Q2
            m = re.search(r'FY(\d{2,4})Q(\d)', f.name, re.IGNORECASE)
            if m:
                year_str = m.group(1)
                quarter = m.group(2)
                year = int(year_str) if len(year_str) == 4 else int("20" + year_str)
                # 尝试匹配可能的目录名格式
                existing.add(f"FY{year}-Q{quarter}")
                existing.add(f"FY{year}-Q{quarter}-Asset-Package")
                existing.add(f"FY{year % 100}q{quarter}")
                existing.add(f"FY{year % 100}q{quarter}-zip")
    return existing


def find_raw_quarters(company: str) -> List[str]:
    """列出原始数据中该公司的所有季度目录，按时间排序。"""
    company_raw_dir = RAW_DATA_DIR / company
    if not company_raw_dir.exists():
        print(f"❌ 错误: 原始数据目录不存在: {company_raw_dir}")
        sys.exit(1)

    quarters = []
    for entry in company_raw_dir.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            quarters.append(entry.name)

    quarters.sort(key=parse_quarter)
    return quarters


def build_output_path(company: str, quarter_dir: str) -> Path:
    """根据季度目录名构建输出文件路径。"""
    company_analysis_dir = ANALYSIS_DIR / company
    company_analysis_dir.mkdir(parents=True, exist_ok=True)

    m = re.search(r'FY(\d{4})-Q(\d)', quarter_dir, re.IGNORECASE)
    if m:
        filename = f"MSFT_FY{m.group(1)[2:]}Q{m.group(2)}.md"
    else:
        m = re.search(r'FY(\d{2})q(\d)', quarter_dir, re.IGNORECASE)
        if m:
            filename = f"MSFT_FY{m.group(1)}Q{m.group(2)}.md"
        else:
            filename = f"MSFT_{quarter_dir}.md"

    return company_analysis_dir / filename


def already_processed(output_path: Path) -> bool:
    """检查输出文件是否已存在且非空。"""
    return output_path.exists() and output_path.stat().st_size > 100


def generate_prompt(company: str, quarter_dir: str) -> str:
    """生成给 Claude 的指令。"""
    raw_path = RAW_DATA_DIR / company / quarter_dir
    return (
        f"请对 {company} 的 {quarter_dir} 季度财报数据包进行深度分析。\n"
        f"数据来源目录: {raw_path}\n"
        f"要求：\n"
        f"1. 读取该目录下的所有文件（Excel、Word、PPT等），提取核心财务数据\n"
        f"2. 分析收入、利润、毛利率、各业务板块表现\n"
        f"3. 总结管理层展望和关键 KPI\n"
        f"4. 用 Markdown 格式输出结构化的财报分析报告\n"
        f"5. 报告使用中文"
    )


def run_claude(prompt: str, output_path: Path, dry_run: bool = False) -> Tuple[int, str]:
    """
    调用 Claude CLI 非交互模式 (-p) 执行分析，并将输出写入文件。
    返回 (exit_code, stderr)。
    """
    cmd = [
        "claude",
        "-p",
        prompt,
        "--allowed-tools", "Read,Bash",
        "--add-dir", str(RAW_DATA_DIR),
        "--add-dir", str(ANALYSIS_DIR),
    ]

    if dry_run:
        print(f"   [Dry Run] 命令: {' '.join(cmd)}")
        print(f"   [Dry Run] 输出将写入: {output_path}")
        return 0, ""

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            process = subprocess.run(
                cmd,
                stdout=f,
                stderr=subprocess.PIPE,
                text=True,
                timeout=1800,  # 10 分钟超时
            )
        return process.returncode, process.stderr
    except subprocess.TimeoutExpired:
        return -1, "超时: Claude 进程在 10 分钟内未结束"
    except Exception as e:
        return -2, str(e)


def generate_report(results: List[dict]) -> Path:
    """生成 batch_report.md 报告。"""
    TODO_DIR.mkdir(parents=True, exist_ok=True)
    report_path = TODO_DIR / "batch_report.md"

    success = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] == "failed"]
    skipped = [r for r in results if r["status"] == "skipped"]

    lines = [
        "# Batch 财报分析处理报告\n",
        f"\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"\n## 成功处理 ({len(success)} 个)\n",
        "\n| 公司 | 季度 | 生成笔记路径 |",
        "|------|------|-------------|",
    ]
    for r in success:
        lines.append(f"| {r['company']} | {r['quarter']} | {r['output_path']} |")

    lines.extend([
        f"\n## 失败 ({len(failed)} 个)\n",
        "\n| 公司 | 季度 | 错误原因 |",
        "|------|------|---------|",
    ])
    for r in failed:
        err = r.get("stderr", "未知错误").replace("\n", " ")[:80]
        lines.append(f"| {r['company']} | {r['quarter']} | {err} |")

    lines.extend([
        f"\n## 跳过（已处理）({len(skipped)} 个)\n",
        "\n| 公司 | 季度 | 已有笔记路径 |",
        "|------|------|-------------|",
    ])
    for r in skipped:
        lines.append(f"| {r['company']} | {r['quarter']} | {r['output_path']} |")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def filter_quarters(
    quarters: List[str],
    year_filter: Optional[str],
    quarter_filter: Optional[str],
) -> List[str]:
    """
    按年份和季度筛选目录列表。
    year_filter: 单个年份如 '2023'，或范围如 '2023-2025'
    quarter_filter: 单个季度如 '1'，或多个如 '1,3,4'
    """
    allowed_years = None
    if year_filter:
        if "-" in year_filter:
            start, end = year_filter.split("-", 1)
            allowed_years = set(range(int(start), int(end) + 1))
        else:
            allowed_years = {int(year_filter)}

    allowed_quarters = None
    if quarter_filter:
        allowed_quarters = {int(q.strip()) for q in quarter_filter.split(",")}

    filtered = []
    for q in quarters:
        year, quarter, _ = parse_quarter(q)
        if allowed_years and year not in allowed_years:
            continue
        if allowed_quarters and quarter not in allowed_quarters:
            continue
        filtered.append(q)
    return filtered


def main():
    parser = argparse.ArgumentParser(description="批量调度 Claude 分析财报")
    parser.add_argument("--company", required=True, help="公司名称，例如 微软")
    parser.add_argument("--dry-run", action="store_true", help="只打印命令，不实际执行")
    parser.add_argument("--force", action="store_true", help="强制重新处理已存在的笔记")
    parser.add_argument(
        "--year",
        dest="year_filter",
        help="指定财年，如 2023 或范围 2023-2025",
    )
    parser.add_argument(
        "--quarter",
        dest="quarter_filter",
        help="指定季度，如 1 或多选 1,3,4",
    )
    args = parser.parse_args()

    company = args.company
    print("=" * 60)
    print("Batch 财报分析调度")
    print("=" * 60)
    print(f"公司: {company}")
    if args.year_filter:
        print(f"年份筛选: {args.year_filter}")
    if args.quarter_filter:
        print(f"季度筛选: Q{args.quarter_filter.replace(',', ', Q')}")
    print(f"模式: {'模拟运行' if args.dry_run else '正常执行'}")
    print()

    quarters = find_raw_quarters(company)
    quarters = filter_quarters(quarters, args.year_filter, args.quarter_filter)
    if not quarters:
        print("⚠️ 未找到任何季度目录（筛选后为空）")
        sys.exit(0)

    results = []
    for quarter_dir in quarters:
        output_path = build_output_path(company, quarter_dir)

        if not args.force and already_processed(output_path):
            print(f"⏭️  跳过 {quarter_dir}（已处理）")
            results.append({
                "company": company,
                "quarter": quarter_dir,
                "status": "skipped",
                "output_path": str(output_path.relative_to(BASE_DIR)),
            })
            continue

        print(f"🚀 正在处理: {quarter_dir}")
        prompt = generate_prompt(company, quarter_dir)
        exit_code, stderr = run_claude(prompt, output_path, dry_run=args.dry_run)

        if args.dry_run:
            results.append({
                "company": company,
                "quarter": quarter_dir,
                "status": "success",
                "output_path": str(output_path.relative_to(BASE_DIR)),
            })
        elif exit_code == 0:
            print(f"✅ 完成: {quarter_dir} -> {output_path}")
            results.append({
                "company": company,
                "quarter": quarter_dir,
                "status": "success",
                "output_path": str(output_path.relative_to(BASE_DIR)),
            })
        else:
            print(f"❌ 失败: {quarter_dir} - claude 退出码 {exit_code}")
            if stderr:
                print(f"   错误信息: {stderr[:200]}")
            results.append({
                "company": company,
                "quarter": quarter_dir,
                "status": "failed",
                "stderr": stderr or f"claude 退出码 {exit_code}",
            })

    print()
    report_path = generate_report(results)
    print(f"📋 报告已生成: {report_path}")

    success_count = len([r for r in results if r["status"] == "success"])
    failed_count = len([r for r in results if r["status"] == "failed"])
    skipped_count = len([r for r in results if r["status"] == "skipped"])

    print(f"\n统计: {success_count} 成功, {failed_count} 失败, {skipped_count} 跳过")

    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
