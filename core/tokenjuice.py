"""
Personal Memory Engine — TokenJuice 智能压缩模块
=================================================
参考OpenHuman TokenJuice设计，针对中文和HTML内容优化。
支持多层压缩策略：HTML→Markdown转换 → 去重 → 折叠 → 摘要

中文优化重点：
- 中文字符按2 token估算
- 保留中文标点、段落结构
- C-Eval-like 质量评分
"""

from __future__ import annotations
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from bs4 import BeautifulSoup
from markdownify import markdownify as md_convert

logger = logging.getLogger(__name__)


class CompressionStrategy(Enum):
    CONVERT = "convert"      # HTML→Markdown
    TRUNCATE = "truncate"    # 截断到最大长度
    DEDUP = "dedup"          # 去重连续相同行
    FOLD = "fold"            # 折叠空白
    DROP_REGEX = "drop_regex"  # 正则匹配丢弃
    SUMMARIZE = "summarize"  # 调用LLM摘要（需external)


@dataclass
class TokenJuiceRule:
    """单条压缩规则"""
    name: str
    order: int
    strategy: CompressionStrategy
    max_chars: int = 50000    # 仅TRUNCATE使用
    pattern: str = ""          # 仅DROP_REGEX使用
    replacement: str = ""      # 仅DROP_REGEX使用


@dataclass
class CompressionResult:
    """压缩结果"""
    original_size: int = 0      # 原始字节
    compressed_size: int = 0    # 压缩后字节
    original_chars: int = 0
    compressed_chars: int = 0
    estimated_tokens_saved: int = 0
    ratio: float = 0.0          # 压缩比 0-1 (1=完全压缩)
    strategies_applied: list[str] = field(default_factory=list)
    output: str = ""
    error: Optional[str] = None

    @property
    def summary(self) -> str:
        return (
            f"压缩: {self.original_chars}→{self.compressed_chars} 字符 "
            f"({self.ratio*100:.0f}%) | "
            f"节省~{self.estimated_tokens_saved} tokens | "
            f"策略: {', '.join(self.strategies_applied)}"
        )


class TokenJuice:
    """
    TokenJuice 压缩引擎
    
    三层规则：
    1. 内置规则 (builtin) — 默认启用
    2. 用户规则 (user) — 用户自定义叠加
    3. 项目规则 (project) — 最高优先级
    """

    BUILTIN_RULES = [
        TokenJuiceRule(name="html_to_markdown", order=1, strategy=CompressionStrategy.CONVERT),
        TokenJuiceRule(name="dedup_lines", order=2, strategy=CompressionStrategy.DEDUP),
        TokenJuiceRule(name="fold_whitespace", order=3, strategy=CompressionStrategy.FOLD),
        TokenJuiceRule(name="drop_boilerplate", order=4, strategy=CompressionStrategy.DROP_REGEX,
                      pattern=r"(?:^(?:Nav|Footer|Sidebar|广告|菜单|导航|页脚|侧栏)[^\n]*\n)+",
                      replacement=""),
        TokenJuiceRule(name="drop_empty_lines", order=5, strategy=CompressionStrategy.DROP_REGEX,
                      pattern=r"\n{3,}",
                      replacement="\n\n"),
        TokenJuiceRule(name="truncate_oversized", order=6, strategy=CompressionStrategy.TRUNCATE,
                      max_chars=50000),
    ]

    def __init__(self, rules: Optional[list[TokenJuiceRule]] = None):
        # 合并规则：内置 + 用户
        rule_map = {r.name: r for r in self.BUILTIN_RULES}
        if rules:
            for r in rules:
                rule_map[r.name] = r  # 用户规则覆盖内置
        self.rules = sorted(rule_map.values(), key=lambda r: r.order)
        self._strategy_map: dict[CompressionStrategy, Callable] = {
            CompressionStrategy.CONVERT: self._strategy_convert,
            CompressionStrategy.TRUNCATE: self._strategy_truncate,
            CompressionStrategy.DEDUP: self._strategy_dedup,
            CompressionStrategy.FOLD: self._strategy_fold,
            CompressionStrategy.DROP_REGEX: self._strategy_drop_regex,
            CompressionStrategy.SUMMARIZE: self._strategy_summarize,
        }

    def compress(self, text: str, is_html: bool = False) -> CompressionResult:
        """
        压缩文本，返回压缩结果
        
        Args:
            text: 原始文本
            is_html: 是否为HTML（自动前置convert）
        """
        result = CompressionResult()
        result.original_size = len(text.encode("utf-8"))
        result.original_chars = len(text)
        
        current = text
        applied = []
        
        # 如果是HTML且第一个规则不是convert，强制先convert
        if is_html and (not self.rules or self.rules[0].strategy != CompressionStrategy.CONVERT):
            current = self._strategy_convert(current)
            applied.append("convert(forced)")
        
        for rule in self.rules:
            strategy_fn = self._strategy_map.get(rule.strategy)
            if not strategy_fn:
                logger.warning(f"Unknown strategy: {rule.strategy}")
                continue
            
            try:
                rule_applied = False
                before = len(current)
                
                if rule.strategy == CompressionStrategy.TRUNCATE:
                    current = strategy_fn(current, rule.max_chars)
                elif rule.strategy == CompressionStrategy.DROP_REGEX:
                    current = strategy_fn(current, rule.pattern, rule.replacement)
                else:
                    current = strategy_fn(current)
                
                if len(current) < before:
                    applied.append(rule.name)
                    rule_applied = True
                    
                logger.debug(f"Rule '{rule.name}': {before}→{len(current)} chars")
            except Exception as e:
                logger.warning(f"Rule '{rule.name}' failed: {e}")
        
        result.strategies_applied = applied
        result.output = current
        result.compressed_size = len(current.encode("utf-8"))
        result.compressed_chars = len(current)
        
        saved_chars = result.original_chars - result.compressed_chars
        # 估算token：中文≈2 char/token，英文≈4 char/token
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', current))
        english_chars = result.compressed_chars - chinese_chars
        result.estimated_tokens_saved = int(
            saved_chars * (chinese_chars / result.compressed_chars * 2 + 
                          english_chars / result.compressed_chars * 0.25)
            if result.compressed_chars > 0 else 0
        )
        result.ratio = 1 - (result.compressed_chars / result.original_chars) if result.original_chars > 0 else 0
        
        return result

    def compress_to_summary(self, text: str, max_chars: int = 500) -> CompressionResult:
        """
        快速摘要模式：只保留前max_chars，适合记忆树预览
        """
        result = self.compress(text)
        if len(result.output) > max_chars:
            result.output = result.output[:max_chars] + "\n\n... [truncated]"
            result.compressed_chars = len(result.output)
        return result

    # ─── 策略实现 ────────────────────────────

    def _strategy_convert(self, text: str) -> str:
        """HTML→Markdown转换，中文保留"""
        # 检查是否真的是HTML
        if not re.search(r'<[^>]+>', text):
            return text
        try:
            soup = BeautifulSoup(text, "html.parser")
            # 去掉无用标签
            for tag in soup(["script", "style", "nav", "footer", "aside", "iframe", "noscript"]):
                tag.decompose()
            md = md_convert(str(soup), heading_style="ATX", strip=["a", "img"])
            # 清理多余空白
            md = re.sub(r'\n{3,}', '\n\n', md)
            return md.strip()
        except Exception as e:
            logger.warning(f"HTML convert failed: {e}")
            return text

    def _strategy_dedup(self, text: str) -> str:
        """去重连续相同行"""
        lines = text.split("\n")
        deduped = []
        prev = ""
        count = 0
        for line in lines:
            stripped = line.strip()
            if stripped == prev:
                count += 1
                if count <= 1:  # 保留第1次重复
                    deduped.append(line)
            else:
                count = 0
                deduped.append(line)
            prev = stripped
        return "\n".join(deduped)

    def _strategy_fold(self, text: str) -> str:
        """折叠空白：多个空格→1个，但保留段落"""
        lines = text.split("\n")
        folded = []
        for line in lines:
            if line.strip() == "":
                folded.append("")
            else:
                folded.append(re.sub(r'[ \t]+', ' ', line).strip())
        return "\n".join(folded)

    def _strategy_truncate(self, text: str, max_chars: int) -> str:
        """截断到最大字符数"""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n... [truncated by TokenJuice]"

    def _strategy_drop_regex(self, text: str, pattern: str, replacement: str) -> str:
        """正则匹配丢弃"""
        if not pattern:
            return text
        return re.sub(pattern, replacement, text, flags=re.MULTILINE)

    def _strategy_summarize(self, text: str) -> str:
        """
        LLM摘要（占位，需配置LLM）
        后续可对接 OpenAI / DeepSeek API
        """
        # TODO: 集成LLM调用
        logger.info("Summarize strategy requires LLM configuration — skipped")
        return text


# 便捷函数
def compress_html(html: str, **kwargs) -> CompressionResult:
    """快捷转换HTML→Markdown→压缩"""
    tj = TokenJuice()
    return tj.compress(html, is_html=True)


def quick_compress(text: str, max_chars: int = 50000) -> CompressionResult:
    """快速压缩，使用默认规则"""
    tj = TokenJuice()
    return tj.compress(text)
