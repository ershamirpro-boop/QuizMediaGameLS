from __future__ import annotations
import os, json, random, uuid, pathlib, mimetypes, io, html
from datetime import datetime
from typing import List, Dict, Any, Optional

import streamlit as st

# ========================= קבועים והגדרות =========================
APP_TITLE = "Quiz Media"
DATA_DIR = pathlib.Path("data")
MEDIA_DIR = pathlib.Path("media")
LOCAL_QUESTIONS_JSON = DATA_DIR / "questions.json"

ADMIN_CODE = os.getenv("ADMIN_CODE", "admin246")
FIXED_N_QUESTIONS = 15

# Supabase דרך Secrets ב-Streamlit Cloud
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "")           # למשל: quiz-media
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

def _now_folder(prefix: str = "media") -> str:
    return datetime.utcnow().strftime(f"{prefix}/%Y/%m")

def _new_name(orig: str) -> str:
    ext = pathlib.Path(orig).suffix.lower()
    return f"{uuid.uuid4().hex}{ext}"

def _ctype(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"

def upload_to_supabase_from_bytes(file_bytes: bytes, original_name: str) -> str:
    sb = _get_supabase(); assert sb is not None, "Supabase לא מוגדר"
    object_path = f"{_now_folder('media')}/{_new_name(original_name)}"
    sb.storage.from_(SUPABASE_BUCKET).upload(
        object_path,
        file=io.BytesIO(file_bytes),
        file_options={"content-type": _ctype(original_name), "x-upsert": "true"},
    )
    return f"sb://{SUPABASE_BUCKET}/{object_path}"

def sign_url_sb(sb_url: str, expires_seconds: int = 300) -> str:
    assert sb_url.startswith("sb://")
    _, bucket, path = sb_url.split("/", 2)
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

def _save_uploaded_to_storage(upload) -> str:
    if _supabase_on():
        return upload_to_supabase_from_bytes(bytes(upload.getbuffer()), upload.name)
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
    try:
        sb.storage.from_(SUPABASE_BUCKET).remove([object_path])
    except Exception:
        pass
    sb.storage.from_(SUPABASE_BUCKET).upload(
        object_path,
        file=io.BytesIO(data),
        file_options={"content-type": content_type, "x-upsert": "true"},
    )

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
        if isinstance(q, dict) and "question" in q and "answers" in q and isinstance(q["answers"], list) and len(q["answers"]) == 4:
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
.block-container{padding-top:10px;padding-bottom:16px;max-width:900px}
h1,h2,h3,h4{text-align:right;letter-spacing:.2px}
label,p,li,.stMarkdown{text-align:right}

/* כפתור התחלה */
.start-btn>button{
  width:100%;padding:14px 16px;font-size:18px;border-radius:12px;
  background:#23C483!important;color:#fff!important;border:0!important
}

/* תשובות 2x2 */
.answer-grid .stButton button{
  width:100%;padding:14px 16px;font-size:18px;border-radius:12px;
  min-height:56px;border:1px solid rgba(0,0,0,.15)
}
.answer-grid .stButton{margin-bottom:10px}

/* סימון בחירה תמיד אדום */
.selected-btn .stButton>button{
  background:#ff4b4b!important;color:#ffffff!important;border-color:#ff4b4b!important;
  box-shadow:0 0 0 3px rgba(255,75,75,.18) inset!important;
}

/* מדיה */
img{max-height:52vh;object-fit:contain}
.video-shell,.audio-shell{width:100%}
.video-shell video,.audio-shell audio{width:100%}

/* פס תחתון */
.bottom-bar{position:sticky;bottom:0;background:rgba(255,255,255,.94);backdrop-filter:blur(6px);padding:10px 8px;border-top:1px solid rgba(0,0,0,.08)}
@media (prefers-color-scheme: dark){.bottom-bar{background:rgba(17,24,39,.9);border-top:1px solid rgba(255,255,255,.08)}}

/* כפתורי סיכום */
.summary-btns .stButton button{width:100%;padding:12px 16px;font-size:16px;border-radius:10px}

/* באדג'ים */
.badge-ok{background:#E8FFF3;border:1px solid #23C483;color:#0b7a56;padding:6px 10px;border-radius:10px;font-size:14px}
.badge-err{background:#FFF0F0;border:1px solid #F44336;color:#a02121;padding:6px 10px;border-radius:10px;font-size:14px}
</style>
""", unsafe_allow_html=True)

# ========================= קונפטי ל-100 =========================
def fire_confetti():
    st.components.v1.html("""
    <div id="__confetti"></div>
    <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js"></script>
    <script>
      (function () {
        const end = Date.now() + 2000;
        (function frame() {
          confetti({ particleCount: 120, spread: 70, origin: { y: 0.6 } });
          if (Date.now() < end) requestAnimationFrame(frame);
        })();
      })();
    </script>
    """, height=0)

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
def _render_media(q: Dict[str, Any], key: str):
    t = q.get("type","text")
    url = q.get("content_url","")
    if not url: return
    signed = _signed_or_raw(url, seconds=300)
    if t=="image": st.image(signed, use_container_width=True)
    elif t=="video": st.video(signed)
    elif t=="audio": st.audio(signed)

# ========================= תשובות 2×2 עם סימון =========================
def render_answer_buttons(q: Dict[str, Any], idx: int, state_key: str = "answers_map"):
    picked = st.session_state.get(state_key, {}).get(idx)
    st.markdown('<div class="answer-grid">', unsafe_allow_html=True)
    col_right, col_left = st.columns(2, vertical_alignment="center")

    def ans_btn(label: str, on_right_col: bool):
        btn_key = f"ans_{state_key}_{idx}_{label}_{'r' if on_right_col else 'l'}"
        wrap_class = "selected-btn" if picked == label else ""
        st.markdown(f'<div class="{wrap_class}">', unsafe_allow_html=True)
        clicked = st.button(label, key=btn_key, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
        if clicked:
            st.session_state.setdefault(state_key, {})[idx] = label
            st.rerun()

    with col_right:
        for i in (0, 2):
            if i < len(q["answers"]):
                ans_btn(q["answers"][i]["text"], True)
    with col_left:
        for i in (1, 3):
            if i < len(q["answers"]):
                ans_btn(q["answers"][i]["text"], False)

    st.markdown('</div>', unsafe_allow_html=True)

# ========================= State helpers =========================
def reset_game_state():
    for k in ["phase","questions","answers_map","current_idx","score","finished","review_idx"]:
        st.session_state.pop(k, None)

def ensure_game_loaded():
    if "questions" not in st.session_state:
        qs = _read_questions()
        st.session_state.questions = _pick_session_questions(qs)
        st.session_state.current_idx = 0
        st.session_state.answers_map = {}
        st.session_state.score = 0
        st.session_state.finished = False

def _get_question_by_id(qid: str) -> Optional[Dict[str,Any]]:
    for q in _read_questions():
        if q.get("id")==qid: return q
    return None

# ========================= UI משתמש רגיל =========================
if "phase" not in st.session_state:
    st.session_state.phase = "welcome"

if st.session_state.phase == "welcome":
    st.title("🎯 משחק טריוויה מדיה")
    st.caption("משחק פתוח ואנונימי. מדיה נטענת באופן פרטי ומאובטח. אין שמירת זהות.")
    st.subheader("ברוך הבא!")
    st.write("לחץ על התחל לשחק כדי להתחיל משחק חדש.")

    st.markdown('<div class="start-btn">', unsafe_allow_html=True)
    if st.button("התחל לשחק"):
        all_q = _read_questions()
        if not all_q:
            st.warning("אין שאלות במאגר כרגע.")
        else:
            ensure_game_loaded()
            st.session_state.phase = "quiz"
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # כניסת מנהלים רק במסך הבית
    if st.button("כניסת מנהלים"):
        st.session_state["admin_mode"] = True
        st.session_state["admin_screen"] = "login"
        st.rerun()

elif st.session_state.phase == "quiz":
    all_q = _read_questions()
    if not all_q or "questions" not in st.session_state:
        st.info("אין שאלות כרגע.")
    else:
        qlist = st.session_state.questions
        idx   = st.session_state.current_idx
        q     = qlist[idx]

        _render_media(q, key=f"q{idx}")
        st.markdown(f"### {q['question']}")
        if q.get("category"):
            st.caption(f"קטגוריה: {q.get('category')} | קושי: {q.get('difficulty','לא צוין')}")

        # תשובות 2x2 עם הדגשת הבחירה
        render_answer_buttons(q, idx, state_key="answers_map")

        # תחתית: שמור והמשך + אפס משחק
        st.markdown('<div class="bottom-bar">', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        next_disabled = (idx not in st.session_state.answers_map)
        if c1.button("שמור והמשך לשאלה הבאה", disabled=next_disabled):
            if idx + 1 >= len(qlist):
                st.session_state.phase = "review"
            else:
                st.session_state.current_idx += 1
            st.rerun()
        if c2.button("אפס משחק"):
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

    render_answer_buttons(q, ridx, state_key="answers_map")

    c_prev, c_next = st.columns(2)
    with c_prev:
        if st.button("← הקודמת", disabled=(ridx==0)):
            st.session_state.review_idx -= 1; st.rerun()
    with c_next:
        if st.button("הבאה →", disabled=(ridx==len(qlist)-1)):
            st.session_state.review_idx += 1; st.rerun()

    st.markdown('<div class="summary-btns">', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("חזור לשאלון"):
            st.session_state.phase = "quiz"; st.rerun()
    with c2:
        if st.button("בדוק אותי"):
            st.session_state.score = _calc_score(st.session_state.questions, st.session_state.answers_map)
            st.session_state.phase = "result"; st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

elif st.session_state.phase == "result":
    total = len(st.session_state.questions); score = st.session_state.score
    pct = int(round(100 * score / max(1,total)))
    st.subheader("תוצאה")
    st.markdown(f"<h1 style='font-size:48px;text-align:center;'>{pct}</h1>", unsafe_allow_html=True)
    if pct == 100:
        st.success("כל הכבוד! 100% מושלם")
        try:
            if hasattr(st, "balloons"):
                st.balloons()
        except Exception:
            pass
        fire_confetti()
    elif pct >= 61:
        st.info("😊 יפה מאוד")
    else:
        st.warning("🫣 קורה לכולם, אולי ננסה שוב?")

    st.divider()
    st.markdown("### פירוט המבחן")
    for i, q in enumerate(st.session_state.questions):
        picked = st.session_state.answers_map.get(i)
        correct_text = next(a["text"] for a in q["answers"] if a.get("is_correct"))
        ok = (picked == correct_text)
        badge = "badge-ok" if ok else "badge-err"
        st.markdown(f"**{i+1}. {q['question']}**")
        _render_media(q, key=f"res{i}")
        st.markdown(f"<span class='{badge}'>תשובה {'נכונה' if ok else 'שגויה'}</span>", unsafe_allow_html=True)
        st.write(f"מה סימנת: {picked if picked else '—'}")
        st.write(f"מה נכון: {correct_text}")
        st.markdown("---")

    c1, c2 = st.columns(2)
    if c1.button("שחק שוב"):
        reset_game_state(); ensure_game_loaded(); st.session_state.phase = "quiz"; st.rerun()
    if c2.button("חזור למסך הבית"):
        reset_game_state(); st.session_state.phase = "welcome"; st.rerun()

# ========================= ממשק אדמין =========================
def admin_login_ui():
    st.subheader("כניסת מנהלים")
    code = st.text_input("קוד מנהל", type="password")
    if st.button("היכנס"):
        if code == ADMIN_CODE:
            st.session_state["admin_screen"] = "menu"
            st.session_state["is_admin"] = True
            st.success("ברוך הבא, מנהל")
            st.rerun()
        else:
            st.error("קוד שגוי")

def admin_menu_ui():
    st.subheader("לוח מנהל")
    c1, c2, c3 = st.columns(3)
    if c1.button("ערוך תוכן"): st.session_state["admin_screen"] = "edit_list"; st.rerun()
    if c2.button("מחק תוכן"): st.session_state["admin_screen"] = "delete_list"; st.rerun()
    if c3.button("הוסף תוכן"): st.session_state["admin_screen"] = "add_form"; st.rerun()

def admin_edit_list_ui():
    st.subheader("ערוך תוכן")
    all_q = _read_questions()
    if not all_q:
        st.info("אין שאלות לעריכה"); return
    options = {f"{i+1}. {q['question'][:80]}": q["id"] for i,q in enumerate(all_q)}
    label = st.selectbox("בחר שאלה לעריכה", list(options.keys()))
    c1, c2 = st.columns(2)
    if c1.button("פתח"):
        st.session_state["admin_edit_qid"] = options[label]
        st.session_state["admin_screen"] = "edit_detail"; st.rerun()
    if c2.button("חזרה"):
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

    st.divider()
    colA, colB, colC = st.columns(3)
    if colA.button("ערוך שינויים"):
        st.session_state["admin_edit_mode"] = True; st.rerun()

    if colB.button("שמור ועדכן שינויים", disabled=not st.session_state.get("admin_edit_mode", False)):
        new_q = dict(q)
        new_q["question"]   = st.session_state.get("edit_q_text", q["question"])
        new_q["category"]   = st.session_state.get("edit_q_cat", q.get("category",""))
        new_q["difficulty"] = st.session_state.get("edit_q_diff", q.get("difficulty",2))

        # רדיו 1..4 → אינדקס 0..3
        correct_index_1based = st.session_state.get("edit_correct_idx", 1)
        correct_index_0based = max(0, min(3, int(correct_index_1based) - 1))

        new_answers = []
        for i in range(4):
            txt = st.session_state.get(f"edit_ans_{i}", q["answers"][i]["text"])
            is_ok = (correct_index_0based == i)
            new_answers.append({"text": txt, "is_correct": is_ok})
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

    if colC.button("חזרה"):
        st.session_state["admin_screen"]="edit_list"; st.session_state.pop("admin_edit_mode", None); st.rerun()

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

        current_media_url = st.session_state.get("edit_q_media_url", q.get("content_url",""))
        st.text_input("נתיב או URL נוכחי", value=current_media_url, key="edit_q_media_url")
        up = st.file_uploader("החלף קובץ", type=["jpg","jpeg","png","gif","mp4","webm","m4a","mp3","wav","ogg"], key="edit_q_upload")
        if up:
            saved = _save_uploaded_to_storage(up)
            st.session_state["edit_q_media_url"] = saved
            st.success(f"הוחלף לקובץ: {saved}")
            preview_url = _signed_or_raw(saved, 300)
        else:
            preview_url = _signed_or_raw(current_media_url, 300)

        tt = st.session_state.get("edit_q_type", t)
        if tt == "image" and preview_url:
            st.image(preview_url, use_container_width=True)
        elif tt == "video" and preview_url:
            st.video(preview_url)
        elif tt == "audio" and preview_url:
            st.audio(preview_url)

def admin_delete_list_ui():
    st.subheader("מחק תוכן")
    all_q = _read_questions()
    if not all_q:
        st.info("אין שאלות למחיקה"); return
    checked_ids = []
    for q in all_q:
        cols = st.columns([0.1, 0.9])
        with cols[0]:
            if st.checkbox("", key=f"chk_{q['id']}"): checked_ids.append(q["id"])
        with cols[1]:
            st.markdown(f"**{q['question'][:110]}**")
            st.caption(f"id: {q['id']} | קטגוריה: {q.get('category','')} | קושי: {q.get('difficulty','')}")
        st.divider()
    if checked_ids and st.button("מחק שאלות"):
        new_list = [x for x in all_q if x.get("id") not in checked_ids]
        _write_questions(new_list)
        st.success("נמחק ושמור")
        st.session_state["admin_screen"]="menu"; st.rerun()
    if st.button("חזרה"):
        st.session_state["admin_screen"]="menu"; st.rerun()

def admin_add_form_ui():
    st.subheader("הוסף תוכן")
    t = st.selectbox("סוג", ["image","video","audio","text"], key="add_type")
    media_url = st.session_state.get("add_media_url", "")

    if t!="text":
        up = st.file_uploader("הוסף קובץ (מומלץ ≤ 2MB, ≤ 5s)", type=["jpg","jpeg","png","gif","mp4","webm","m4a","mp3","wav","ogg"], key="add_upload")
        if up:
            media_url = _save_uploaded_to_storage(up)
            st.session_state["add_media_url"] = media_url
            st.success(f"קובץ נשמר: {media_url}")
            signed = _signed_or_raw(media_url, 300)
            if t=="image": st.image(signed, use_container_width=True)
            elif t=="video": st.video(signed)
            elif t=="audio": st.audio(signed)

        media_url = st.text_input("או הדבק URL", value=media_url, key="add_media_url")

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
    st.markdown("**תצוגה מקדימה**")
    preview = {"type": t, "content_url": media_url, "question": q_text,
               "answers": [{"text": a_vals[i], "is_correct": (i+1)==correct_idx_1based} for i in range(4)]}
    _render_media(preview, key="add_preview")
    st.markdown(f"### {q_text if q_text else '...'}")
    colR, colL = st.columns(2)
    with colR:
        for i in [0,2]:
            if i<len(a_vals):
                cls = "badge-ok" if (i+1)==correct_idx_1based else "badge-err"
                st.markdown(f"<div class='{cls}' style='margin-bottom:8px'>{html.escape(a_vals[i])}</div>", unsafe_allow_html=True)
    with colL:
        for i in [1,3]:
            if i<len(a_vals):
                cls = "badge-ok" if (i+1)==correct_idx_1based else "badge-err"
                st.markdown(f"<div class='{cls}' style='margin-bottom:8px'>{html.escape(a_vals[i])}</div>", unsafe_allow_html=True)

    st.divider()
    if st.button("שמור ועדכן"):
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
            # איפוס שדות ההוספה
            for k in list(st.session_state.keys()):
                if k.startswith("add_"): st.session_state.pop(k, None)
            st.session_state["admin_screen"]="menu"; st.rerun()
    if st.button("חזרה"):
        st.session_state["admin_screen"]="menu"; st.rerun()

# ניהול מוד אדמין – מופעל רק אם נכנסת מהבית
if st.session_state.get("admin_mode"):
    st.divider()
    screen = st.session_state.get("admin_screen","login")
    if screen == "login": admin_login_ui()
    elif screen == "menu": admin_menu_ui()
    elif screen == "edit_list": admin_edit_list_ui()
    elif screen == "edit_detail": admin_edit_detail_ui()
    elif screen == "delete_list": admin_delete_list_ui()
    elif screen == "add_form": admin_add_form_ui()
