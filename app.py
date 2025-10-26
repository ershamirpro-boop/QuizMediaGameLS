from __future__ import annotations
import os, json, random, uuid, pathlib, html, mimetypes, tempfile
from datetime import datetime
from typing import List, Dict, Any, Optional

import streamlit as st

# ========================= קבועים והגדרות =========================
APP_TITLE = "Quiz Media"

DATA_DIR = pathlib.Path("data")
MEDIA_DIR = pathlib.Path("media")
LOCAL_QUESTIONS_JSON = DATA_DIR / "questions.json"

ADMIN_CODE = os.getenv("ADMIN_CODE", "admin246")  # ניתן לשנות בסיקרטס
FIXED_N_QUESTIONS = 15

# Supabase (דרך Secrets)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "")           # לדוגמה: quiz-media
QUESTIONS_OBJECT_PATH = os.getenv("QUESTIONS_OBJECT_PATH", "data/questions.json")

DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# ========================= Supabase עזרי אחסון =========================
_supabase = None
def _supabase_on() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and SUPABASE_BUCKET)

def _get_supabase():
    global _supabase
    if _supabase is None and _supabase_on():
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _supabase

def _sb_object_to_sburl(bucket: str, object_path: str) -> str:
    return f"sb://{bucket}/{object_path}"

def _sburl_split(sb_url: str) -> tuple[str, str]:
    # sb://bucket/path/to/file
    _, bucket, path = sb_url.split("/", 2)
    return bucket, path

def sign_url_sb(sb_url: str, expires_seconds: int = 300) -> str:
    assert sb_url.startswith("sb://")
    bucket, path = _sburl_split(sb_url)
    sb = _get_supabase(); assert sb is not None
    res = sb.storage.from_(bucket).create_signed_url(path, expires_seconds)
    return res.get("signedURL") or res.get("signed_url") or ""

def _save_uploaded_file_local(upload) -> str:
    ext = pathlib.Path(upload.name).suffix.lower()
    name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}{ext}"
    path = MEDIA_DIR / name
    with open(path, "wb") as f:
        f.write(upload.getbuffer())
    return str(path).replace("\\", "/")

def upload_to_supabase_path(tmp_path: str, original_name: str) -> str:
    """מעלה לקובץ מהדיסק (זמני) – הכי יציב מול הספרייה."""
    sb = _get_supabase(); assert sb is not None, "Supabase לא מוגדר"
    ext = pathlib.Path(original_name).suffix.lower()
    folder = datetime.utcnow().strftime("media/%Y/%m")
    object_path = f"{folder}/{uuid.uuid4().hex}{ext}"
    sb.storage.from_(SUPABASE_BUCKET).upload(object_path, tmp_path)
    return _sb_object_to_sburl(SUPABASE_BUCKET, object_path)

def _save_uploaded_to_storage(upload) -> str:
    """אם יש Supabase – מעלה לשם; אחרת, שומר בקובץ מקומי."""
    if not upload:
        return ""
    if _supabase_on():
        # כותבים לקובץ זמני ואז מעלים – מונע בעיות כותרות/סוגים
        suffix = pathlib.Path(upload.name).suffix or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(upload.getbuffer())
            tmp_path = tmp.name
        try:
            return upload_to_supabase_path(tmp_path, upload.name)
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    # ללא Supabase – שמירה מקומית
    return _save_uploaded_file_local(upload)

def _signed_or_raw(url: str, seconds: int = 300) -> str:
    if url.startswith("sb://") and _supabase_on():
        return sign_url_sb(url, seconds)
    return url

# ========================= מאגר שאלות: ענן או מקומי =========================
def _sb_download_bytes(object_path: str) -> bytes:
    sb = _get_supabase(); assert sb is not None
    return sb.storage.from_(SUPABASE_BUCKET).download(object_path)

def _sb_upload_bytes(object_path: str, data: bytes, content_type: str = "application/json; charset=utf-8"):
    sb = _get_supabase(); assert sb is not None
    # מוחקים אם קיים (שקט)
    try:
        sb.storage.from_(SUPABASE_BUCKET).remove([object_path])
    except Exception:
        pass
    # כותבים ל-temp ואז מעלים (עוקף בעיות headers)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        sb.storage.from_(SUPABASE_BUCKET).upload(object_path, tmp_path)
    finally:
        try: os.remove(tmp_path)
        except Exception: pass

def _read_questions() -> List[Dict[str, Any]]:
    if _supabase_on():
        try:
            raw = _sb_download_bytes(QUESTIONS_OBJECT_PATH)
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = []
            _write_questions(data)
    else:
        if not LOCAL_QUESTIONS_JSON.exists():
            LOCAL_QUESTIONS_JSON.write_text("[]", encoding="utf-8")
        data = json.loads(LOCAL_QUESTIONS_JSON.read_text(encoding="utf-8"))

    clean = []
    for q in data:
        if (isinstance(q, dict)
            and "question" in q
            and "answers" in q
            and isinstance(q["answers"], list)
            and len(q["answers"]) == 4):
            clean.append(q)
    return clean

def _write_questions(all_q: List[Dict[str, Any]]) -> None:
    payload = json.dumps(all_q, ensure_ascii=False, indent=2).encode("utf-8")
    if _supabase_on():
        _sb_upload_bytes(QUESTIONS_OBJECT_PATH, payload)
    else:
        LOCAL_QUESTIONS_JSON.write_bytes(payload)

# ========================= עיצוב כללי =========================
st.set_page_config(page_title=APP_TITLE, page_icon="🎯", layout="wide")
st.markdown("""
<style>
.stApp{direction:rtl}
.block-container{padding-top:10px;padding-bottom:16px;max-width:980px}
h1,h2,h3,h4{text-align:right;letter-spacing:.2px}
label,p,li,.stMarkdown{text-align:right}
.answer-grid .stButton{margin-bottom:10px}
.zoom-wrap{position:relative;display:inline-block;width:100%}
.zoom-btn{position:absolute;top:10px;left:10px;z-index:2;padding:6px 10px;font-size:14px;border-radius:10px;background:rgba(0,0,0,.55);color:#fff;border:1px solid rgba(255,255,255,.4);cursor:pointer}
.lightbox-overlay{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;z-index:9999}
.lightbox-overlay.show{display:flex}
.lightbox-content{max-width:96vw;max-height:92vh}
.lightbox-content img{width:100%;height:auto;object-fit:contain}
.lightbox-close{position:fixed;top:12px;right:12px;z-index:10000;background:rgba(0,0,0,.65);color:#fff;border:1px solid rgba(255,255,255,.4);padding:6px 10px;border-radius:10px;cursor:pointer;font-size:16px}
.bottom-bar{position:sticky;bottom:0;background:rgba(255,255,255,.94);backdrop-filter:blur(6px);padding:10px 8px;border-top:1px solid rgba(0,0,0,.08)}
@media (prefers-color-scheme: dark){.bottom-bar{background:rgba(17,24,39,.9);border-top:1px solid rgba(255,255,255,.08)}}
.summary-btns .stButton button{width:100%;padding:12px 16px;font-size:16px;border-radius:10px}
.badge-ok{background:#E8FFF3;border:1px solid #23C483;color:#0b7a56;padding:6px 10px;border-radius:10px;font-size:14px}
.badge-err{background:#FFF0F0;border:1px solid #F44336;color:#a02121;padding:6px 10px;border-radius:10px;font-size:14px}
img{max-height:52vh;object-fit:contain}
.video-shell,.audio-shell{width:100%}
.video-shell video,.audio-shell audio{width:100%}
</style>
""", unsafe_allow_html=True)

# ========================= Utilities =========================
def reset_admin_state():
    for k in ["admin_mode","admin_screen","admin_edit_mode","admin_edit_qid"]:
        st.session_state.pop(k, None)

def _pick_session_questions(all_q: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not all_q: return []
    k = min(FIXED_N_QUESTIONS, len(all_q))
    chosen = random.sample(all_q, k=k)
    for q in chosen: random.shuffle(q["answers"])
    return chosen

def _calc_score(questions: List[Dict[str, Any]], answers_map: Dict[int, str]) -> int:
    score = 0
    for i, q in enumerate(questions):
        picked = answers_map.get(i)
        if picked is None: continue
        correct_text = next(a["text"] for a in q["answers"] if a.get("is_correct"))
        if picked == correct_text: score += 1
    return score

# ========================= מדיה לתצוגה =========================
def _image_with_lightbox(url: str, key: str):
    element_id = f"img_{key}"
    overlay_id = f"lb_{key}"
    close_id = f"lb_close_{key}"
    st.markdown(f"""
<div class="zoom-wrap">
  <button class="zoom-btn" id="{element_id}_zoom">הגדלה</button>
  <img id="{element_id}" src="{html.escape(url)}" alt="image" />
</div>
<div class="lightbox-overlay" id="{overlay_id}">
  <div class="lightbox-content">
    <img src="{html.escape(url)}" alt="image-full" />
  </div>
  <button class="lightbox-close" id="{close_id}">✕</button>
</div>
<script>
(function(){{
  const img=document.getElementById("{element_id}");
  const btn=document.getElementById("{element_id}_zoom");
  const ovl=document.getElementById("{overlay_id}");
  const cls=document.getElementById("{close_id}");
  if(!img||!btn||!ovl||!cls) return;
  function openLB(){{ovl.classList.add("show")}}
  function closeLB(){{ovl.classList.remove("show")}}
  img.addEventListener("click",openLB);
  btn.addEventListener("click",openLB);
  cls.addEventListener("click",closeLB);
  ovl.addEventListener("click",e=>{{if(e.target===ovl) closeLB();}});
  document.addEventListener("keydown",e=>{{if(e.key==="Escape") closeLB();}});
}})();
</script>
""", unsafe_allow_html=True)

def _video_or_audio_with_autoplay(url: str, tag: str, key: str):
    element_id = f"media_{key}"
    controls = "controlslist='nodownload noplaybackrate'"
    st.markdown(f"""
<div class="{tag}-shell">
  <<TAG> id="{element_id}" {controls} playsinline preload="auto" src="{html.escape(url)}"></<TAG>>
</div>
""".replace("<TAG>", tag), unsafe_allow_html=True)

def _render_media(q: Dict[str, Any], key: str):
    t = q.get("type","text")
    url = q.get("content_url","")
    if not url: return
    signed = _signed_or_raw(url, seconds=300)
    if t=="image": _image_with_lightbox(signed, key)
    elif t=="video": _video_or_audio_with_autoplay(signed, "video", key)
    elif t=="audio": _video_or_audio_with_autoplay(signed, "audio", key)

# ========================= State helpers =========================
def reset_game_state():
    for k in ["phase","questions","answers_map","current_idx","score","finished","review_idx","session_questions"]:
        st.session_state.pop(k, None)

def ensure_game_loaded():
    if "questions" not in st.session_state:
        qs = _read_questions()
        st.session_state.session_questions = _pick_session_questions(qs)
        st.session_state.questions = st.session_state.session_questions  # לשימוש קצר
        st.session_state.current_idx = 0
        st.session_state.answers_map = {}
        st.session_state.score = 0
        st.session_state.finished = False

# ========================= Header =========================
st.title("🎯 משחק טריוויה מדיה")
st.caption("משחק פתוח ואנונימי. מדיה נטענת באופן פרטי ומאובטח. אין שמירת זהות.")

# כפתור כניסת מנהלים
col_top_left, col_top_right = st.columns([3,1])
with col_top_right:
    if st.button("כניסת מנהלים"):
        st.session_state["admin_mode"] = True
        st.session_state["admin_screen"] = "login"
        st.rerun()

# אם לא במצב אדמין - ננקה מצבים
if not st.session_state.get("admin_mode"):
    for k in ["admin_screen","admin_edit_mode","admin_edit_qid"]:
        st.session_state.pop(k, None)

# ========================= UI משתמש רגיל =========================
if not st.session_state.get("admin_mode"):
    all_q = _read_questions()
    if "phase" not in st.session_state: st.session_state.phase = "welcome"

    if st.session_state.phase == "welcome":
        st.subheader("ברוך הבא!")
        st.write("תיאור קצר של המשחק... אפשר לעדכן בהמשך.")
        if st.button("התחל לשחק", type="primary", use_container_width=True):
            if not all_q:
                st.warning("אין שאלות במאגר כרגע.")
            else:
                ensure_game_loaded()
                st.session_state.phase = "quiz"
                st.rerun()

    elif st.session_state.phase == "quiz":
        if not all_q or "questions" not in st.session_state:
            st.info("אין שאלות כרגע.")
        else:
            qlist = st.session_state.questions
            idx = st.session_state.current_idx
            q = qlist[idx]

            _render_media(q, key=f"q{idx}")
            st.markdown(f"### {q['question']}")
            if q.get("category"):
                st.caption(f"קטגוריה: {q.get('category')} | קושי: {q.get('difficulty','לא צוין')}")

            picked = st.session_state.answers_map.get(idx)

            # 2×2 כפתורים עם הדגשה של הבחירה (primary)
            st.markdown('<div class="answer-grid">', unsafe_allow_html=True)
            col1, col2 = st.columns(2, vertical_alignment="center")

            def btn(label: str, key_suffix: str) -> bool:
                return st.button(
                    label,
                    key=f"ans_{idx}_{key_suffix}",
                    use_container_width=True,
                    type=("primary" if picked == label else "secondary"),
                )

            with col1:
                if btn(q["answers"][0]["text"], "0"):
                    st.session_state.answers_map[idx] = q["answers"][0]["text"]; st.rerun()
            with col2:
                if btn(q["answers"][1]["text"], "1"):
                    st.session_state.answers_map[idx] = q["answers"][1]["text"]; st.rerun()
            with col1:
                if btn(q["answers"][2]["text"], "2"):
                    st.session_state.answers_map[idx] = q["answers"][2]["text"]; st.rerun()
            with col2:
                if btn(q["answers"][3]["text"], "3"):
                    st.session_state.answers_map[idx] = q["answers"][3]["text"]; st.rerun()

            st.markdown('<div class="bottom-bar">', unsafe_allow_html=True)
            c1, c2, c3 = st.columns([1,1,1])
            if c1.button("חזור"):
                if idx > 0:
                    st.session_state.current_idx -= 1
                st.rerun()
            if c2.button("שמור והבא", disabled=(idx not in st.session_state.answers_map)):
                if idx + 1 >= len(qlist):
                    st.session_state.phase = "review"
                else:
                    st.session_state.current_idx += 1
                st.rerun()
            if c3.button("אפס משחק"):
                reset_game_state(); st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    elif st.session_state.phase == "review":
        st.subheader("סקירה לפני הגשה")
        qlist = st.session_state.questions
        if "review_idx" not in st.session_state: st.session_state.review_idx = 0
        ridx = st.session_state.review_idx
        q = qlist[ridx]

        st.write(f"שאלה {ridx+1} מתוך {len(qlist)}")
        _render_media(q, key=f"rev{ridx}")
        st.markdown(f"**{q['question']}**")
        current_pick = st.session_state.answers_map.get(ridx)

        cols = st.columns([1,1,1])
        if cols[0].button("← הקודמת", disabled=(ridx==0)):
            st.session_state.review_idx -= 1; st.rerun()
        if cols[1].button("חזור"):
            st.session_state.phase = "quiz"; st.rerun()
        if cols[2].button("הבאה →", disabled=(ridx==len(qlist)-1)):
            st.session_state.review_idx += 1; st.rerun()

        st.markdown('<div class="answer-grid">', unsafe_allow_html=True)
        col1, col2 = st.columns(2, vertical_alignment="center")

        def rev_btn(label: str, key_suffix: str) -> bool:
            return st.button(
                label,
                key=f"rev_{ridx}_{key_suffix}",
                use_container_width=True,
                type=("primary" if current_pick == label else "secondary"),
            )

        with col1:
            if rev_btn(q["answers"][0]["text"], "0"):
                st.session_state.answers_map[ridx] = q["answers"][0]["text"]; st.rerun()
        with col2:
            if rev_btn(q["answers"][1]["text"], "1"):
                st.session_state.answers_map[ridx] = q["answers"][1]["text"]; st.rerun()
        with col1:
            if rev_btn(q["answers"][2]["text"], "2"):
                st.session_state.answers_map[ridx] = q["answers"][2]["text"]; st.rerun()
        with col2:
            if rev_btn(q["answers"][3]["text"], "3"):
                st.session_state.answers_map[ridx] = q["answers"][3]["text"]; st.rerun()

        st.markdown('<div class="summary-btns">', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        if c1.button("בדוק אותי", type="primary"):
            st.session_state.score = _calc_score(st.session_state.questions, st.session_state.answers_map)
            st.session_state.phase = "result"; st.rerun()
        if c2.button("חזור למשחק"):
            st.session_state.phase = "quiz"; st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    elif st.session_state.phase == "result":
        total = len(st.session_state.questions); score = st.session_state.score
        pct = int(round(100 * score / max(1,total)))
        st.subheader("תוצאה")
        st.markdown(f"<h1 style='font-size:48px;text-align:center;'>{pct}</h1>", unsafe_allow_html=True)
        if pct == 100:
            st.success("כל הכבוד!"); st.balloons()
        elif pct >= 61:
            st.info("😊 יפה מאוד")
        else:
            st.warning("🫣 קורה לכולם, ננסה שוב?")

        st.divider()
        st.markdown("### פירוט המבחן (מה סומנה ומה נכון)")
        for i, q in enumerate(st.session_state.questions):
            picked = st.session_state.answers_map.get(i)
            correct = next(a["text"] for a in q["answers"] if a.get("is_correct"))
            st.markdown(f"**{i+1}. {q['question']}**")
            if q.get("type") == "image" and q.get("content_url"):
                st.image(_signed_or_raw(q["content_url"], 300), use_container_width=True)
            elif q.get("type") == "video" and q.get("content_url"):
                st.video(_signed_or_raw(q["content_url"], 300))
            elif q.get("type") == "audio" and q.get("content_url"):
                st.audio(_signed_or_raw(q["content_url"], 300))
            ok = (picked == correct)
            st.markdown(
                ("<div class='badge-ok'>תשובה נכונה</div>" if ok else "<div class='badge-err'>תשובה שגויה</div>"),
                unsafe_allow_html=True
            )
            st.write(f"**מה סומנה:** {picked if picked is not None else '—'}")
            st.write(f"**מה נכון:** {correct}")
            st.divider()

        c1, c2 = st.columns(2)
        if c1.button("שחק שוב"):
            reset_game_state(); ensure_game_loaded(); st.session_state.phase = "quiz"; st.rerun()
        if c2.button("סיום"):
            reset_game_state(); st.session_state.phase = "welcome"; st.rerun()

# ========================= ממשק אדמין =========================
def admin_login_ui():
    st.subheader("כניסת מנהלים")
    code = st.text_input("קוד מנהל", type="password")
    cols = st.columns(2)
    if cols[0].button("היכנס", type="primary"):
        if code == ADMIN_CODE:
            st.session_state["admin_screen"] = "menu"
            st.session_state["is_admin"] = True
            st.success("ברוך הבא, מנהל")
            st.rerun()
        else:
            st.error("קוד שגוי")
    if cols[1].button("חזור"):
        reset_admin_state(); st.rerun()

def admin_menu_ui():
    st.subheader("לוח מנהל")
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("הוסף תוכן", type="primary"): st.session_state["admin_screen"] = "add_form"; st.rerun()
    if c2.button("ערוך תוכן"): st.session_state["admin_screen"] = "edit_list"; st.rerun()
    if c3.button("מחק תוכן"): st.session_state["admin_screen"] = "delete_list"; st.rerun()
    if c4.button("יציאה"): reset_admin_state(); st.rerun()

def _get_question_by_id(qid: str) -> Optional[Dict[str,Any]]:
    for q in _read_questions():
        if q.get("id")==qid: return q
    return None

def admin_edit_list_ui():
    st.subheader("ערוך תוכן")
    all_q = _read_questions()
    if not all_q:
        st.info("אין שאלות לעריכה"); 
        if st.button("חזור"): st.session_state["admin_screen"] = "menu"; st.rerun()
        return
    options = {f"{i+1}. {q['question'][:80]}": q["id"] for i,q in enumerate(all_q)}
    label = st.selectbox("בחר שאלה לעריכה", list(options.keys()))
    c1, c2 = st.columns(2)
    if c1.button("פתח", type="primary"):
        st.session_state["admin_edit_qid"] = options[label]
        st.session_state["admin_screen"] = "edit_detail"; st.rerun()
    if c2.button("חזור"):
        st.session_state["admin_screen"] = "menu"; st.rerun()

def admin_edit_detail_ui():
    qid = st.session_state.get("admin_edit_qid")
    q = _get_question_by_id(qid)
    if not q:
        st.error("השאלה לא נמצאה"); st.session_state["admin_screen"]="edit_list"; return

    st.subheader("תצוגת שאלה ועריכה")
    _render_media(q, key=f"adm_{qid}")
    st.markdown(f"### {q['question']}")
    st.caption(f"קטגוריה: {q.get('category','')} | קושי: {q.get('difficulty','')}")

    col1, col2 = st.columns(2)
    ans = q["answers"]
    def colored(label: str, ok: bool):
        css = "badge-ok" if ok else "badge-err"
        st.markdown(f"<div class='{css}' style='margin-bottom:8px'>{html.escape(label)}</div>", unsafe_allow_html=True)
    with col1:
        for a in ans[::2]: colored(a["text"], a.get("is_correct",False))
    with col2:
        for a in ans[1::2]: colored(a["text"], a.get("is_correct",False))

    # ----- מצב עריכה -----
    st.divider()
    colA, colB, colC, colD = st.columns(4)
    if colA.button("ערוך"):
        st.session_state["admin_edit_mode"] = True; st.rerun()
    if colB.button("חזור"):
        st.session_state["admin_screen"]="edit_list"; st.session_state.pop("admin_edit_mode", None); st.rerun()

    if colC.button("שמור", disabled=not st.session_state.get("admin_edit_mode", False), type="primary"):
        new_q = dict(q)
        new_q["question"]   = st.session_state.get("edit_q_text", q["question"])
        new_q["category"]   = st.session_state.get("edit_q_cat", q.get("category",""))
        new_q["difficulty"] = st.session_state.get("edit_q_diff", q.get("difficulty",2))

        # רדיו 1..4 -> 0..3
        correct_index_1based = st.session_state.get("edit_correct_idx", 1)
        ci = max(0, min(3, int(correct_index_1based) - 1))

        new_answers = []
        for i in range(4):
            txt = st.session_state.get(f"edit_ans_{i}", q["answers"][i]["text"])
            new_answers.append({"text": txt, "is_correct": (ci == i)})
        new_q["answers"] = new_answers

        new_q["type"]        = st.session_state.get("edit_q_type", q.get("type","text"))
        new_q["content_url"] = st.session_state.get("edit_q_media_url", q.get("content_url",""))

        all_q = _read_questions()
        for i,row in enumerate(all_q):
            if row.get("id")==qid: all_q[i]=new_q; break
        _write_questions(all_q)
        st.success("עודכן ושמור")
        st.session_state["admin_edit_mode"] = False
        st.rerun()

    if colD.button("רענן"):
        st.rerun()

    if st.session_state.get("admin_edit_mode", False):
        st.markdown("### מצב עריכה")
        st.text_input("מלל השאלה", value=q["question"], key="edit_q_text")
        st.text_input("קטגוריה", value=q.get("category",""), key="edit_q_cat")
        st.number_input("קושי", min_value=1, max_value=5, value=int(q.get("difficulty",2)), key="edit_q_diff")

        st.markdown("**תשובות**")
        cols = st.columns(4)
        for i,c in enumerate(cols):
            with c:
                st.text_input(f"תשובה {i+1}", value=q["answers"][i]["text"], key=f"edit_ans_{i}")

        correct_idx0 = next((i for i in range(4) if q["answers"][i].get("is_correct")), 0)
        st.radio("סמן נכונה", options=[1,2,3,4], index=correct_idx0, key="edit_correct_idx", horizontal=True)

        st.divider()
        st.markdown("**מדיה**")
        t = q.get("type","text")
        st.selectbox("סוג", ["image","video","audio","text"], index=["image","video","audio","text"].index(t), key="edit_q_type")
        st.text_input("URL / נתיב", value=q.get("content_url",""), key="edit_q_media_url")
        up = st.file_uploader("החלף קובץ (≤200MB)", type=["jpg","jpeg","png","gif","mp4","webm","m4a","mp3","wav","ogg"], key="edit_q_upload")
        if up:
            saved = _save_uploaded_to_storage(up)
            st.session_state["edit_q_media_url"] = saved
            st.success(f"נשמר: {saved}")
            prev = _signed_or_raw(saved, 300)
        else:
            prev = _signed_or_raw(st.session_state.get("edit_q_media_url", q.get("content_url","")), 300)
        if st.session_state.get("edit_q_type", t) == "image" and prev:
            st.image(prev, use_container_width=True)
        elif st.session_state.get("edit_q_type", t) == "video" and prev:
            st.video(prev)
        elif st.session_state.get("edit_q_type", t) == "audio" and prev:
            st.audio(prev)

def admin_delete_list_ui():
    st.subheader("מחק תוכן")
    all_q = _read_questions()
    if not all_q:
        st.info("אין שאלות למחיקה")
        if st.button("חזור"): st.session_state["admin_screen"]="menu"; st.rerun()
        return
    checked_ids = []
    for q in all_q:
        cols = st.columns([0.1, 0.9])
        with cols[0]:
            if st.checkbox("", key=f"chk_{q['id']}"): checked_ids.append(q["id"])
        with cols[1]:
            st.markdown(f"**{q['question'][:110]}**")
            st.caption(f"id: {q['id']} | קטגוריה: {q.get('category','')} | קושי: {q.get('difficulty','')}")
        st.divider()
    c1, c2, c3 = st.columns(3)
    if c1.button("מחק", type="primary") and checked_ids:
        new_list = [x for x in all_q if x.get("id") not in checked_ids]
        _write_questions(new_list)
        st.success("נמחק ושמור"); st.session_state["admin_screen"]="menu"; st.rerun()
    if c2.button("רענן"): st.rerun()
    if c3.button("חזור"): st.session_state["admin_screen"]="menu"; st.rerun()

def admin_add_form_ui():
    st.subheader("הוסף תוכן")
    t = st.selectbox("סוג", ["image","video","audio","text"], key="add_type")
    media_url = st.session_state.get("add_media_url", "")
    if t!="text":
        up = st.file_uploader("הוסף קובץ (≤200MB)", type=["jpg","jpeg","png","gif","mp4","webm","m4a","mp3","wav","ogg"], key="add_upload")
        if up:
            media_url = _save_uploaded_to_storage(up)
            st.session_state["add_media_url"] = media_url
            st.success(f"קובץ נשמר: {media_url}")
            signed = _signed_or_raw(media_url, 300)
            if t=="image": st.image(signed, use_container_width=True)
            elif t=="video": st.video(signed)
            elif t=="audio": st.audio(signed)
        media_url = st.text_input("או הדבק URL", value=media_url, key="add_media_url_input")
        if media_url:
            st.session_state["add_media_url"] = media_url
    q_text = st.text_input("טקסט השאלה", key="add_q_text")

    st.markdown("**תשובות**")
    cols = st.columns(4)
    a_vals = []
    for i,c in enumerate(cols):
        with c:
            a_vals.append(st.text_input(f"תשובה {i+1}", key=f"add_ans_{i}"))

    correct_idx_1based = st.radio("סמן נכונה", options=[1,2,3,4], index=0, horizontal=True, key="add_correct_idx")
    category = st.text_input("קטגוריה (אופציונלי)", value="", key="add_cat")
    difficulty = st.number_input("קושי 1-5", min_value=1, max_value=5, value=2, key="add_diff")

    st.divider()
    st.markdown("**תצוגת תצוגה מקדימה**")
    preview = {"type": t, "content_url": media_url, "question": q_text,
               "answers": [{"text": a_vals[i] if i<len(a_vals) else "", "is_correct": (i+1)==correct_idx_1based} for i in range(4)]}
    _render_media(preview, key="add_preview")
    st.markdown(f"### {q_text if q_text else '...'}")
    st.markdown('<div class="answer-grid">', unsafe_allow_html=True)
    cL, cR = st.columns(2)
    def _badge(txt, ok):
        cls = "badge-ok" if ok else "badge-err"
        st.markdown(f"<div class='{cls}' style='margin-bottom:8px'>{html.escape(txt)}</div>", unsafe_allow_html=True)
    with cL:
        for i in [0,2]:
            if i<len(a_vals): _badge(a_vals[i], (i+1)==correct_idx_1based)
    with cR:
        for i in [1,3]:
            if i<len(a_vals): _badge(a_vals[i], (i+1)==correct_idx_1based)

    st.divider()
    c1, c2 = st.columns(2)
    if c1.button("שמור ועדכן", type="primary"):
        if not q_text or any(not x for x in a_vals):
            st.error("חובה למלא שאלה ו-4 תשובות")
        elif t!="text" and not media_url:
            st.error("לשאלת מדיה חובה לצרף קובץ או URL")
        else:
            all_q = _read_questions()
            new_item = {
                "id": uuid.uuid4().hex,
                "type": t,
                "content_url": media_url if t!="text" else "",
                "question": q_text,
                "answers": [{"text": a_vals[i], "is_correct": (i+1)==correct_idx_1based} for i in range(4)],
                "category": category,
                "difficulty": difficulty,
                "created_at": datetime.utcnow().isoformat()
            }
            all_q.append(new_item)
            _write_questions(all_q)
            st.success("נשמר למאגר")
            st.session_state["admin_screen"]="menu"; st.rerun()
    if c2.button("חזור"):
        st.session_state["admin_screen"]="menu"; st.rerun()

# ניהול ניווט אדמין
if st.session_state.get("admin_mode"):
    st.divider()
    screen = st.session_state.get("admin_screen","login")
    if screen == "login": admin_login_ui()
    elif screen == "menu": admin_menu_ui()
    elif screen == "edit_list": admin_edit_list_ui()
    elif screen == "edit_detail": admin_edit_detail_ui()
    elif screen == "delete_list": admin_delete_list_ui()
    elif screen == "add_form": admin_add_form_ui()
