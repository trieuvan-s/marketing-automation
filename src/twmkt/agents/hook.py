"""Hook Agent — sinh HOOK marketing sắc, ngắn, target đúng nhà đầu tư.

Chất lượng thật đến từ LLM (Sonnet/content_model). Fallback tất định chỉ để chạy
$0 khi offline/lùi mượt, nhưng đã bỏ kiểu chung chung ("thị trường: <tiêu đề>")
— dẫn bằng dữ kiện/số nổi bật.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import load_brand
from ._jsonparse import try_json_object as _try_json
from .base import Agent

# Content Factory Phase D (vá rò brand cũ) — tên brand đọc từ config/brand.yaml
# (MỘT NGUỒN), KHÔNG hard-code brand nào (cũ hay mới) — xem agents/production.py
# ._BRAND_NAME cho cùng nếp + lý do đọc 1 LẦN lúc import module.
_BRAND_NAME = str(load_brand().get("name") or "").strip() or "đội ngũ phân tích"
_DEFAULT_CTA = f"Theo dõi {_BRAND_NAME} để cập nhật phân tích."

# dữ kiện gây chú ý: số tiền/%/kỷ lục
_NUM_RE = re.compile(r"(\d[\d.,]*\s*(?:%|tỷ|nghìn tỷ|triệu|usd|đồng)|kỷ lục|cao nhất|thấp nhất)",
                     re.IGNORECASE)


@dataclass
class MarketingHook:
    topic: str
    angle: str
    headlines: list[str] = field(default_factory=list)
    audience: str = "nhà đầu tư cá nhân"
    emotion: str = "tò mò"
    cta: str = _DEFAULT_CTA


_SYSTEM = (
    f"PERSONA: Bạn là Trưởng nhóm nội dung mạng xã hội của {_BRAND_NAME} — quỹ đầu "
    "tư giá trị cho nhà đầu tư cá nhân Việt Nam. Giọng: sắc bén, đáng tin, đi thẳng "
    "vào dữ kiện; văn phong người-thật, không PR sáo rỗng. Mục tiêu: viết HOOK khiến "
    "nhà đầu tư DỪNG LƯỚT và muốn đọc tiếp.\n"
    "QUY TẮC:\n"
    "- Mở đầu bằng dữ kiện/con số GÂY CHÚ Ý NHẤT trong bài (số tiền, %, kỷ lục, tên mã).\n"
    "- Tạo khoảng trống tò mò: nói đủ để tò mò, GIỮ LẠI điểm mấu chốt.\n"
    "- Sắc, tự tin, cụ thể. KHÔNG sáo rỗng, TUYỆT ĐỐI KHÔNG mở bằng 'thị trường:'.\n"
    "- MỖI tiêu đề NGẮN (≤140 ký tự), đứng một mình vẫn hiểu.\n"
    "- Trung lập, KHÔNG hứa/khuyến nghị lợi nhuận.\n"
    '3 headline theo 3 kiểu: [dẫn-bằng-số, câu-hỏi-tò-mò, góc-tương-phản].\n'
    "VÍ DỤ (few-shot):\n"
    "Input: Tiêu đề bài: HPG lãi quý 3 tăng 40%, cao nhất 8 quý | Mã: HPG\n"
    'Output: {"angle":"Dẫn bằng mức lãi cao nhất 8 quý của HPG để soi động lực '
    'thép","headlines":["HPG lãi quý 3 tăng 40% — cao nhất 8 quý","Điều gì kéo lợi '
    'nhuận Hòa Phát lên đỉnh 2 năm?","Thép hồi phục hay chỉ nền thấp cùng kỳ?"],'
    f'"audience":"nhà đầu tư cá nhân","emotion":"tò mò","cta":"{_DEFAULT_CTA}"' + '}\n'
    "Input: Tiêu đề bài: Nhập siêu 13,8 tỷ USD sau 5 tháng | Mã: (không)\n"
    'Output: {"angle":"Dẫn bằng con số nhập siêu 13,8 tỷ USD để nói về áp lực tỷ '
    'giá","headlines":["Nhập siêu 13,8 tỷ USD sau 5 tháng: điều ít ai để ý","Con số '
    '13,8 tỷ USD nói gì về tỷ giá cuối năm?","Xuất khẩu mạnh nhưng vì sao vẫn nhập '
    'siêu?"],"audience":"nhà đầu tư cá nhân","emotion":"lo ngại",'
    f'"cta":"{_DEFAULT_CTA}"' + '}\n'
    'Trả về DUY NHẤT JSON: {"angle": str, "headlines": [3 chuỗi], "audience": str, '
    '"emotion": str, "cta": str}. Không thêm chữ nào ngoài JSON.'
)


def _article_title(brief) -> str:
    """Tiêu đề BÀI giữ lại (key_points[0]) — KHÔNG dùng 'topic' tra cứu thô."""
    kps = getattr(brief, "key_points", None) or []
    if kps and str(kps[0]).strip():
        return str(kps[0]).strip()
    return (getattr(brief, "topic", "") or "").strip()


class HookAgent(Agent):
    role = "HookStrategist"
    system = _SYSTEM

    # Debug (xem scripts/review_to_sheet.py --debug): lưu prompt/raw response của
    # LẦN GỌI GẦN NHẤT để soi tại sao rơi về fallback (rỗng? không phải JSON?).
    last_prompt: str = ""
    last_raw: str = ""

    def run(self, brief) -> MarketingHook:
        prompt = (
            f"Tiêu đề bài: {_article_title(brief)}\n"
            f"Luận điểm: {getattr(brief, 'thesis', '')}\n"
            f"Mã liên quan: {', '.join(getattr(brief, 'tickers', []))}\n"
            f"Trích đoạn: {' '.join(getattr(brief, 'evidence', [])[:2])[:400]}\n\n"
            "CHỈ trả JSON, KHÔNG markdown, KHÔNG lời dẫn."
        )
        raw = self._ask(prompt)
        self.last_prompt, self.last_raw = prompt, raw   # debug: soi lại lần gọi gần nhất
        data = _try_json(raw)
        if data:
            return MarketingHook(
                topic=_article_title(brief),
                angle=str(data.get("angle", "")).strip()[:200],
                headlines=[str(h).strip()[:140] for h in (data.get("headlines") or [])][:3],
                audience=str(data.get("audience", "nhà đầu tư cá nhân")).strip(),
                emotion=str(data.get("emotion", "tò mò")).strip(),
                cta=str(data.get("cta", _DEFAULT_CTA)).strip() or _DEFAULT_CTA,
            )
        return _fallback(brief)


def _fallback(brief) -> MarketingHook:
    """Không LLM: dẫn bằng dữ kiện nổi bật + BÁM tiêu đề bài (không kiểu chung chung)."""
    title = _article_title(brief)
    tickers = getattr(brief, "tickers", [])
    subject = tickers[0] if tickers else None
    m = _NUM_RE.search(title)
    lead = m.group(0) if m else None

    h1 = title if not subject else f"{subject}: {title}"
    h2 = (f"Con số {lead} nói lên điều gì?" if lead
          else f"Vì sao {subject or 'tin này'} đáng chú ý ngay lúc này?")
    h3 = f"Điều ít nhà đầu tư để ý phía sau: {title[:80]}"
    angle = (f"Dẫn bằng {lead}: {title}" if lead
             else f"Bóc tách ý nghĩa với nhà đầu tư: {title}")
    return MarketingHook(topic=title, angle=angle, headlines=[h1[:140], h2[:140], h3[:140]])
