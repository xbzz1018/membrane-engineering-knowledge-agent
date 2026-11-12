"""Deterministic MD/DOCX views of an approved snapshot; no model calls here."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import uuid
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from src.domain.project_plan import PlanContent

MIME = {"md": "text/markdown; charset=utf-8", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def blocks(record):
    """Both formats consume this same sequence; all prose is already approved."""
    content = PlanContent.model_validate(record["content"])
    requirements = content.requirements
    yield "title", requirements.project_name
    yield "paragraph", "本文件用于项目初步方案讨论。需求为用户声明，正文为方案建议，来源原文单独列示；人工批准绑定本文件标注的方案版本。"
    yield "paragraph", f"方案 {record['plan_id']}　版本 v{record['version']}"
    yield "heading", "需求声明"
    yield "table", [("字段", "声明值", "来源性质"),
                    ("用途", requirements.purpose, "用户声明"),
                    ("面积", f"{requirements.building_area_m2:g} m²" if requirements.building_area_m2 else "待确认", "用户声明"),
                    ("地点", requirements.location or "待确认", "用户声明"),
                    ("膜材偏好", requirements.preferred_membrane or "待确认", "用户声明"),
                    ("适用版次", requirements.applicable_revision or "待确认", "用户声明")]
    if requirements.notes:
        yield "paragraph", "需求原文及补充说明：" + requirements.notes
    for section in content.sections:
        yield "heading", section.title
        yield "paragraph", "方案建议：" + section.content
    yield "heading", "原始依据"
    evidence = {item["evidence_id"]: item for item in record["manifest"]["evidence"]}
    for quote in content.source_quotes:
        source = evidence[quote.evidence_id]
        label = "历史参考" if quote.purpose == "history" else "材料依据"
        yield "paragraph", f"{label}　{source['filename']}　{source['location']}　来源版本 {source['version'] or '未声明'}"
        yield "paragraph", "原文摘录：" + quote.quote
        yield "metadata", "Evidence ID：" + quote.evidence_id
        yield "metadata", "原文 SHA256：" + source["content_sha256"]
    yield "heading", "版本与复核记录"
    decision = record["decision"]
    yield "paragraph", "审查范围为初步方案内容一致性与已实现的规则检查。人工批准不替代后续工程设计及专业审签。"
    yield "metadata", "审查 ID：" + record["review"]["id"]
    yield "metadata", "批准人：" + decision["actor"]
    yield "metadata", "批准说明：" + decision["reason"]
    yield "metadata", "内容 SHA256：" + record["content_hash"]
    yield "metadata", "来源快照 SHA256：" + record["manifest_hash"]


class ProjectDocumentService:
    def __init__(self, store):
        self.settings = store.settings

    def render(self, record, format):
        if record["status"] != "approved" or not record["decision"] or not record["decision"]["consumed"]:
            raise ValueError("文档服务只接受已批准的同版本快照")
        content_blocks = list(blocks(record))
        if format == "md":
            lines = []
            for kind, value in content_blocks:
                if kind == "table":
                    for index, row in enumerate(value):
                        cells = [str(cell).replace("|", "\\|").replace("\n", "<br>") for cell in row]
                        lines.append("| " + " | ".join(cells) + " |")
                        if index == 0:
                            lines.append("| --- | --- | --- |")
                    lines.append("")
                else:
                    prefix = "# " if kind == "title" else "## " if kind == "heading" else ""
                    lines.extend([prefix + value, ""])
            return ("\n".join(lines) + "\n").encode("utf-8")
        if format != "docx":
            raise ValueError("不支持的导出格式")
        document = Document()
        # python-docx's bundled styles include a theme-coloured paragraph rule.
        # Remove it instead of inheriting a decorative line below the title.
        for border in document.styles.element.xpath(".//w:pBdr"):
            border.getparent().remove(border)
        section = document.sections[0]
        section.page_width, section.page_height = Inches(8.5), Inches(11)
        section.top_margin = section.bottom_margin = Inches(0.8)
        section.left_margin = section.right_margin = Inches(0.85)
        for style_name in ("Normal", "Title", "Subtitle", "Heading 1", "Heading 2", "Header", "Footer"):
            style = document.styles[style_name]
            style.font.name = "Arial"
            style.font.color.rgb = RGBColor(0, 0, 0)
            style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        document.styles["Normal"].font.size = Pt(11)
        document.styles["Normal"].paragraph_format.line_spacing = 1.15
        document.styles["Normal"].paragraph_format.space_after = Pt(6)
        document.styles["Title"].font.size = Pt(22)
        document.styles["Heading 1"].font.size = Pt(14)
        header = section.header.paragraphs[0]
        header.text = f"项目初步方案　v{record['version']}"
        footer = section.footer.paragraphs[0]
        footer.text = "项目初步方案　|　"
        page = OxmlElement("w:fldSimple")
        page.set(qn("w:instr"), "PAGE")
        footer._p.append(page)
        for kind, value in content_blocks:
            if kind == "table":
                table = document.add_table(rows=0, cols=3)
                table.style = "Table Grid"
                table.autofit = False
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                for column, width in zip(table.columns, (1.1, 4.35, 1.35), strict=True):
                    column.width = Inches(width)
                for index, row in enumerate(value):
                    cells = table.add_row().cells
                    for cell, text in zip(cells, row, strict=True):
                        cell.text = str(text)
                        for paragraph in cell.paragraphs:
                            paragraph.paragraph_format.space_before = Pt(4)
                            paragraph.paragraph_format.space_after = Pt(4)
                        margins = OxmlElement("w:tcMar")
                        for edge in ("top", "left", "bottom", "right"):
                            item = OxmlElement("w:" + edge)
                            item.set(qn("w:w"), "100")
                            item.set(qn("w:type"), "dxa")
                            margins.append(item)
                        cell._tc.get_or_add_tcPr().append(margins)
                    if index == 0:
                        repeat = OxmlElement("w:tblHeader")
                        table.rows[0]._tr.get_or_add_trPr().append(repeat)
                        for cell in cells:
                            shade = OxmlElement("w:shd")
                            shade.set(qn("w:fill"), "EDEDED")
                            cell._tc.get_or_add_tcPr().append(shade)
                            for run in cell.paragraphs[0].runs:
                                run.bold = True
                document.add_paragraph()
            elif kind == "title":
                document.add_paragraph(value, "Title")
            elif kind == "heading":
                document.add_heading(value, level=1)
            else:
                paragraph = document.add_paragraph(value)
                if kind == "metadata":
                    paragraph.paragraph_format.space_after = Pt(3)
                    paragraph.paragraph_format.line_spacing = 1.0
                    for run in paragraph.runs:
                        run.font.size = Pt(10)
        document.core_properties.author = "资料智能审查平台"
        document.core_properties.title = content_blocks[0][1]
        document.core_properties.subject = f"{record['plan_id']} v{record['version']}"
        output = io.BytesIO()
        document.save(output)
        return output.getvalue()

    async def store(self, artifact, data):
        sha = hashlib.sha256(data).hexdigest()
        filename = f"{artifact['plan_id']}-v{artifact['version']}.{artifact['format']}"
        if self.settings.RUNTIME_MODE.lower() == "full":
            from src.infrastructure.full_backends import get_full_backends

            key = await get_full_backends().store_document(
                artifact["id"], filename, MIME[artifact["format"]], data,
                content_sha=sha, version=artifact["version"],
            )
        else:
            path = self.settings.upload_path / "plan-artifacts" / artifact["id"] / f"{sha}.{artifact['format']}"

            def save():
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp-" + uuid.uuid4().hex)
                try:
                    temporary.write_bytes(data)
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)

            await asyncio.to_thread(save)
            key = str(path.resolve())
        return key, sha

    async def read(self, artifact):
        if self.settings.RUNTIME_MODE.lower() == "full":
            from src.infrastructure.full_backends import get_full_backends

            path = await get_full_backends().materialize_document(
                artifact["object_key"], artifact["id"], "plan." + artifact["format"],
            )
        else:
            path = Path(artifact["object_key"]).resolve()
            root = (self.settings.upload_path / "plan-artifacts").resolve()
            if not path.is_relative_to(root):
                raise ValueError("产物路径不属于文档存储目录")
        data = await asyncio.to_thread(path.read_bytes)
        if len(data) != artifact["byte_size"] or hashlib.sha256(data).hexdigest() != artifact["sha256"]:
            raise ValueError("产物完整性校验失败")
        return data
