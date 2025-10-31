from __future__ import annotations
import os, json, random, uuid, pathlib, html, mimetypes, tempfile, io, time
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import streamlit as st

# ========================= קבועים והגדרות =========================
APP_TITLE = "Quiz Media"
DATA_DIR = pathlib.Path("data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR = pathlib.Path("media"); MEDIA_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_QUESTIONS_JSON = DATA_DIR / "questions.json"

ADMIN_CODE = os.getenv("ADMIN_CODE", "admin246")
FIXED_N_QUESTIONS = 15

# Supabase - אופציונלי דרך Secrets
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "")
QUESTIONS_OBJECT_PATH = os.getenv("QUESTIONS_OBJECT_PATH", "data/questions.json")

def _supabase_on() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and SUPABASE_BUCKET)

# ========================= Flash notifications =========================
def flash(kind: str, msg: str):
    # kind: success|info|warning|error
    st.session_state["_flash"] = {"kind": kind, "msg": msg}

def show_flash():
    data = st.session_state.pop("_flash", None)
    if not data: return
    kind = data.get("kind", "info"); msg = data.get("msg", "")
    if hasattr(st, "toast"):
        icon = {"success":"✅","info":"ℹ️","warning":"⚠️","error":"❌"}.get(kind, "ℹ️")
        st.toast(msg, icon=icon)
    else:
        {"success": st.success, "info": st.info, "warning": st.warning, "error": st.error}.get(kind, st.info)(msg)

# ========================= ביצועים והגנות =========================
st.set_page_config(page_title=APP_TITLE, page_icon="🎯", layout="wide")
show_flash()

# ========================= CSS =========================
st.markdown("""
<style>
.stApp{direction:rtl}
.block-container{padding-top:10px;padding-bottom:16px;max-width:900px}
h1,h2,h3,h4{text-align:right;letter-spacing:.2px}
label,p,li,.stMarkdown{text-align:right}

/* כפתור התחל */
.start-btn>button{
  width:100%;padding:14px 16px;font-size:18px;border-radius:12px;
  background:#23C483!important;color:#fff!important;border:0!important
}

/* גריד 2x2 לרדיו */
.answer-wrap [role="radiogroup"]{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:10px;
}

/* רדיו כמו כפתורים */
.answer-wrap [role="radio"]{
  display:flex; flex-direction:row-reverse; align-items:center; gap:10px;
  width:100%; min-height:64px; padding:12px 14px; box-sizing:border-box;
  border:1px solid rgba(0,0,0,.15); border-radius:12px;
  background:rgba(255,255,255,.03);
  cursor:pointer; user-select:none; transition:all .12s ease-in-out; direction:rtl;
}
.answer-wrap [role="radio"] > div:first-child{ transform:scale(1.15); }
.answer-wrap [role="radio"] > div:nth-child(2){
  flex:1; text-align:center; font-size:20px; line-height:1.25;
}
.answer-wrap [role="radio"][aria-checked="true"]{
  background:#9ee5ff !important; color:#000 !important; border-color:#0099cc !important;
  box-shadow:0 0 0 3px rgba(0,153,204,.35) inset !important; font-weight:700 !important;
}
.answer-wrap [role="radio"]:hover{ box-shadow:0 0 0 2px rgba(0,0,0,.06) inset; }
.answer-wrap [role="radio"]:focus-visible{ outline:3px solid rgba(59,130,246,.55); outline-offset:2px; }

/* פס תחתון */
.bottom-bar{
  position:sticky;bottom:0;background:rgba(255,255,255,.94);
  backdrop-filter:blur(6px);padding:10px 8px;border-top:1px solid rgba(0,0,0,.08)
}
@media (prefers-color-scheme: dark){
  .bottom-bar{background:rgba(17,24,39,.9);border-top:1px solid rgba(255,255,255,.08)}
}

/* תגיות */
.summary-btns .stButton button{width:100%;padding:12px 16px;font-size:16px;border-radius:10px}
.badge-ok{background:#E8FFF3;border:1px solid #23C483;color:#0b7a56;padding:6px 10px;border-radius:10px;font-size:14px}
.badge-err{background:#FFF0F0;border:1px solid #F44336;color:#a02121;padding:6px 10px;border-radius:10px;font-size:14px}

/* CTA גדול */
.primary-cta .stButton>button{
  width:100%;padding:16px 18px;font-size:20px;border-radius:12px;
  background:#ff006b !important;color:#fff !important;border:0 !important
}

/* מובייל */
@media (max-width:520px){
  .answer-wrap [role="radiogroup"]{grid-template-columns:1fr}
}

/* מדיה */
img{max-height:52vh;object-fit:contain}
.video-shell,.audio-shell{width:100%}
.video-shell video,.audio-shell audio{width:100%}

/* לינק חלופי קטן */
.alt-link{font-size:12px;margin-top:6px;display:block;opacity:.8}
</style>
""", unsafe_allow_html=True)

# ========================= Supabase: client (cache) =========================
@st.cache_resource(show_spinner=False)
def _get_supabase():
    if not _supabase_on():
        return None
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ========================= Signed URL cache קטן ומהיר =========================
# כדי להאיץ טעינת תמונות וסרטונים, עם TTL קצר כדי לא לשבור חתימות
@st.cache_data(ttl=120, show_spinner=False)
def _signed_cached(sb_url: str, seconds: int = 300) -> str:
    sb = _get_supabase(); assert sb is not None
    _, bucket, path = sb_url.split("/", 2)
    res = sb.storage.from_(bucket).create_signed_url(path, seconds)
    return res.get("signedURL") or res.get("signed_url") or ""

def _sburl(bucket: str, object_path: str) -> str:
    return f"sb://{bucket}/{object_path}"

def _split_sburl(sb_url: str) -> Tuple[str,str]:
    _, b, p = sb_url.split("/", 2)
    return b, p

def sign_url_sb(sb_url: str, expires_seconds: int = 300) -> str:
    assert sb_url.startswith("sb://")
    # נשתמש בcache כדי להיות מהירים
    return _signed_cached(sb_url, expires_seconds)

def _signed_or_raw(url: str, seconds: int = 300) -> str:
    if url and url.startswith("sb://") and _supabase_on():
        return sign_url_sb(url, seconds)
    return url

# ========================= Prefetch למדיה הבאה =========================
def _prefetch_media(url: str, mtype: str):
    # נשתמש ב<link rel="preload"> כדי לרמוז לדפדפן לטעון מראש
    if not url: return
    as_attr = "image" if mtype == "image" else "video" if mtype == "video" else "audio"
    st.markdown(f"<link rel='preload' as='{as_attr}' href='{html.escape(url)}' />", unsafe_allow_html=True)

def _prefetch_next_question(qlist: List[Dict[str,Any]], idx: int):
    nxt = idx + 1
    if nxt >= len(qlist): return
    qn = qlist[nxt]
    t = qn.get("type", "text")
    url = _signed_or_raw(qn.get("content_url",""), 300)
    if t in {"image","video","audio"} and url:
        _prefetch_media(url, t)

# ========================= העלאות מאובטחות + HEIC→JPEG =========================
def _ensure_jpeg_for_heic(upload) -> Tuple[bytes, str, str]:
    name = upload.name
    raw = upload.getbuffer()
    ext = pathlib.Path(name).suffix.lower()
    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"

    if ext in {".heic", ".heif"}:
        try:
            from PIL import Image
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except Exception:
                pass
            im = Image.open(io.BytesIO(raw))
            im = im.convert("RGB")
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=92, optimize=True)
            jpeg_bytes = out.getvalue()
            new_name = pathlib.Path(name).with_suffix(".jpg").name
            return jpeg_bytes, new_name, "image/jpeg"
        except Exception:
            return bytes(raw), name, content_type
    else:
        return bytes(raw), name, content_type

def _save_uploaded_file_local(upload) -> str:
    file_bytes, name, _ = _ensure_jpeg_for_heic(upload)
    ext = pathlib.Path(name).suffix.lower()
    fn = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}{ext}"
    path = MEDIA_DIR / fn
    with open(path, "wb") as f:
        f.write(file_bytes)
    return str(path).replace("\\", "/")

def _upload_bytes_to_supabase(object_path: str, file_bytes: bytes, content_type: str) -> str:
    sb = _get_supabase(); assert sb is not None
    # חשוב: file_options מחרוזות
    file_options = {"contentType": content_type, "upsert": "true"}
    sb.storage.from_(SUPABASE_BUCKET).upload(object_path, file_bytes, file_options=file_options)
    return _sburl(SUPABASE_BUCKET, object_path)

def _save_uploaded_to_storage(upload) -> str:
    if not upload: return ""
    file_bytes, fixed_name, content_type = _ensure_jpeg_for_heic(upload)
    if _supabase_on():
        folder = datetime.utcnow().strftime("media/%Y/%m")
        ext = pathlib.Path(fixed_name).suffix.lower()
        object_path = f"{folder}/{uuid.uuid4().hex}{ext}"
        return _upload_bytes_to_supabase(object_path, file_bytes, content_type)
    # מקומי
    class _Tmp:
        name = fixed_name
        def getbuffer(self): return file_bytes
    return _save_uploaded_file_local(_Tmp())

# ========================= DB: קריאה/כתיבה עם cache =========================
@st.cache_data(ttl=60, show_spinner=False)
def _read_questions_cached() -> List[Dict[str, Any]]:
    if _supabase_on():
        try:
            sb = _get_supabase(); assert sb is not None
            raw = sb.storage.from_(SUPABASE_BUCKET).download(QUESTIONS_OBJECT_PATH)
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = []
    else:
        if not LOCAL_QUESTIONS_JSON.exists():
            LOCAL_QUESTIONS_JSON.write_text("[]", encoding="utf-8")
        data = json.loads(LOCAL_QUESTIONS_JSON.read_text(encoding="utf-8"))

    clean = []
    for q in data:
        if isinstance(q, dict) and "question" in q and isinstance(q.get("answers"), list) and len(q["answers"]) == 4:
            clean.append(q)
    return clean

def _write_questions(all_q: List[Dict[str, Any]]) -> None:
    payload = json.dumps(all_q, ensure_ascii=False, indent=2).encode("utf-8")
    if _supabase_on():
        sb = _get_supabase(); assert sb is not None
        file_options = {"contentType": "application/json; charset=utf-8", "upsert": "true"}
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
            tmp.write(payload)
            tmp_path = tmp.name
        try:
            sb.storage.from_(SUPABASE_BUCKET).upload(QUESTIONS_OBJECT_PATH, tmp_path, file_options=file_options)
        finally:
            try: os.remove(tmp_path)
            except Exception: pass
    else:
        LOCAL_QUESTIONS_JSON.write_bytes(payload)
    _read_questions_cached.clear()

# ========================= Utilities =========================
def reset_admin_state():
    for k in ["admin_mode","admin_screen","admin_edit_mode","admin_edit_qid"]:
        st.session_state.pop(k, None)

def reset_game_state():
    # נקה מפתחות מצב כלליים
    for k in ["phase","questions","answers_map","current_idx","score","finished","review_idx"]:
        st.session_state.pop(k, None)

    # נקה מפתחות פר־שאלה שמושפעים מהאיטרציה הקודמת
    junk_prefixes = ("ans_map_", "quiz_radio_", "review_radio_")
    to_delete = [k for k in list(st.session_state.keys()) if k.startswith(junk_prefixes)]
    for k in to_delete:
        st.session_state.pop(k, None)

def ensure_game_loaded():
    if "questions" not in st.session_state:
        qs = _read_questions_cached()
        k = min(FIXED_N_QUESTIONS, len(qs))
        chosen = random.sample(qs, k=k) if k > 0 else []
        for q in chosen:
            random.shuffle(q["answers"])
        st.session_state.questions = chosen
        st.session_state.current_idx = 0
        st.session_state.answers_map = {}
        st.session_state.score = 0
        st.session_state.finished = False

def _calc_score(questions: List[Dict[str, Any]], answers_map: Dict[int, str]) -> int:
    score = 0
    for i, q in enumerate(questions):
        picked = answers_map.get(i)
        if picked is None: continue
        correct_text = next(a["text"] for a in q["answers"] if a.get("is_correct"))
        if picked == correct_text: score += 1
    return score

# ========================= רנדר מדיה - עם וידאו מושתק =========================
def _render_media(q: Dict[str, Any], key: str):
    t = q.get("type","text")
    url = q.get("content_url","")
    if not url: return
    signed = _signed_or_raw(url, seconds=300)

    if t == "image":
        st.image(signed, use_container_width=True)
    elif t == "video":
        # HTML5 video מושתק, שומר על פרטיות, מאפשר הפעלה ידנית
        st.markdown(
            f"""
            <div class="video-shell">
              <video src="{html.escape(signed)}" muted playsinline controls preload="metadata"></video>
              <a class="alt-link" href="{html.escape(signed)}" target="_blank" rel="noopener">
                סרטון לא עובד? לחץ כאן
              </a>
            </div>
            """,
            unsafe_allow_html=True
        )
    elif t == "audio":
        # אודיו ללא השתקה
        st.audio(signed)

# ========================= רדיו יציב - בלי צורך בקליק כפול =========================
def answers_grid(question: Dict[str, Any], q_index: int, key_prefix: str):
    opts = [a["text"] for a in question["answers"]]
    map_key = f"ans_map_{q_index}"
    # נייצב את המצב הראשוני פעם אחת
    if map_key not in st.session_state:
        st.session_state[map_key] = st.session_state.get("answers_map", {}).get(q_index)

    # נגזור אינדקס אם יש ערך קיים
    current_val = st.session_state[map_key]
    idx = opts.index(current_val) if current_val in opts else None

    st.markdown('<div class="answer-wrap">', unsafe_allow_html=True)
    picked = st.radio(
        label="בחר תשובה",
        options=opts,
        index=idx,
        key=f"{key_prefix}_radio_{q_index}",
        label_visibility="collapsed",
    )
    st.markdown('</div>', unsafe_allow_html=True)

    # אם הערך השתנה נעדכן מפה וסטייט
    if picked != st.session_state.get(map_key):
        st.session_state[map_key] = picked
        st.session_state.answers_map[q_index] = picked

# ========================= Header =========================
st.title("🎯 משחק טריוויה מדיה")
st.caption("משחק פתוח ואנונימי. מדיה נטענת באופן פרטי ומאובטח. אין שמירת זהות.")

# הצעת כניסת מנהלים במסך הפתיחה בלבד
show_admin_entry = (st.session_state.get("phase","welcome") == "welcome")
if show_admin_entry:
    col_top_left, col_top_right = st.columns([3,1])
    with col_top_right:
        if st.button("כניסת מנהלים", key="admin_entry"):
            st.session_state["admin_mode"] = True
            st.session_state["admin_screen"] = "login"
            st.rerun()

# איפוס מצבי אדמין כשלא באדמין
if not st.session_state.get("admin_mode"):
    for k in ["admin_screen","admin_edit_mode","admin_edit_qid"]:
        st.session_state.pop(k, None)

# ========================= UI משתמש רגיל =========================
if not st.session_state.get("admin_mode"):
    all_q = _read_questions_cached()
    if "phase" not in st.session_state: st.session_state.phase = "welcome"

    if st.session_state.phase == "welcome":
        st.subheader("ברוך הבא!")
        st.write("תיאור קצר של המשחק... אפשר לעדכן בהמשך.")
        st.markdown('<div class="start-btn">', unsafe_allow_html=True)
        if st.button("התחל לשחק"):
            if not all_q:
                st.warning("אין שאלות במאגר כרגע.")
            else:
                ensure_game_loaded()
                st.session_state.phase = "quiz"
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    elif st.session_state.phase == "quiz":
        if not all_q or "questions" not in st.session_state:
            st.info("אין שאלות כרגע.")
        else:
            qlist = st.session_state.questions
            idx = st.session_state.current_idx
            if idx >= len(qlist):
                st.session_state.current_idx = max(0, len(qlist)-1); st.rerun()
            q = qlist[idx]

            _render_media(q, key=f"q{idx}")
            st.markdown(f"### {q['question']}")
            if q.get("category"):
                st.caption(f"קטגוריה: {q.get('category')} | קושי: {q.get('difficulty','לא צוין')}")

            # תשובות
            answers_grid(q, idx, key_prefix="quiz")

            # Prefetch למדיה של השאלה הבאה
            _prefetch_next_question(qlist, idx)

            # פס תחתון
            st.markdown('<div class="bottom-bar">', unsafe_allow_html=True)
            c_left, c_mid, c_right = st.columns(3)
            with c_left:
                if st.button("↩︎ הקודם", disabled=(idx == 0)):
                    st.session_state.current_idx -= 1; st.rerun()
            with c_mid:
                if st.button("שמור בחירה והמשך", disabled=(idx not in st.session_state.answers_map)):
                    if idx + 1 >= len(qlist):
                        st.session_state.phase = "review"
                    else:
                        st.session_state.current_idx += 1
                    st.rerun()
            with c_right:
                if st.button("אפס משחק"):
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

        answers_grid(q, ridx, key_prefix="review")
        _prefetch_next_question(qlist, ridx)

        cols = st.columns(2)
        with cols[0]:
            if st.button("← הקודם", disabled=(ridx==0)):
                st.session_state.review_idx -= 1; st.rerun()
        with cols[1]:
            if st.button("הבא →", disabled=(ridx==len(qlist)-1)):
                st.session_state.review_idx += 1; st.rerun()

        st.divider()
        st.markdown('<div class="primary-cta">', unsafe_allow_html=True)
        if st.button("בדוק אותי 💥", key="check_exam_big"):
            st.session_state.score = _calc_score(st.session_state.questions, st.session_state.answers_map)
            st.session_state.phase = "result"; st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    elif st.session_state.phase == "result":
        qlist = st.session_state.questions
        total = len(qlist); score = _calc_score(qlist, st.session_state.answers_map)
        pct = int(round(100 * score / max(1,total)))
        st.subheader("תוצאה")
        st.markdown(f"<h1 style='font-size:48px;text-align:center;'>{pct}</h1>", unsafe_allow_html=True)
        if pct == 100:
            st.success("כל הכבוד!"); st.balloons(); st.snow()
        elif pct >= 61:
            st.info("😊 יפה מאוד")
        else:
            st.warning("🫣 קורה לכולם, אולי ננסה שוב?")

        st.divider()
        st.markdown("### פירוט המבחן")
        for i, q in enumerate(qlist):
            picked = st.session_state.answers_map.get(i, "-")
            correct = next(a["text"] for a in q["answers"] if a.get("is_correct"))
            ok = (picked == correct)
            st.markdown(f"**{i+1}. {q['question']}**")
            _render_media(q, key=f"res{i}")
            st.info(("✅ תשובה נכונה" if ok else "❌ תשובה שגויה"))
            st.markdown(f"- מה סימנת: **{html.escape(picked)}**")
            st.markdown(f"- מה נכון: **{html.escape(correct)}**")
            st.divider()

        c1, c2 = st.columns(2)
        if c1.button("שחק שוב"):
            reset_game_state(); ensure_game_loaded(); st.session_state.phase = "quiz"; st.rerun()
        if c2.button("חזור למסך הבית"):
            reset_game_state(); st.session_state.phase = "welcome"; st.rerun()

# ========================= ממשק אדמין =========================
def admin_login_ui():
    st.subheader("כניסת מנהלים")
    code = st.text_input("קוד מנהל", type="password")
    cols = st.columns(2)
    if cols[0].button("היכנס"):
        if code == ADMIN_CODE:
            st.session_state["admin_screen"] = "menu"
            st.session_state["is_admin"] = True
            flash("success", "התחברת בהצלחה"); st.rerun()
        else:
            flash("error", "קוד שגוי"); st.rerun()
    if cols[1].button("חזרה"):
        reset_admin_state(); st.rerun()

def admin_menu_ui():
    st.subheader("לוח מנהל")
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("הוסף תוכן"): st.session_state["admin_screen"] = "add_form"; st.rerun()
    if c2.button("ערוך תוכן"): st.session_state["admin_screen"] = "edit_list"; st.rerun()
    if c3.button("מחק תוכן"): st.session_state["admin_screen"] = "delete_list"; st.rerun()
    if c4.button("יציאה"): reset_admin_state(); flash("success","יצאת מממשק מנהל"); st.rerun()

def _get_question_by_id(qid: str) -> Optional[Dict[str,Any]]:
    for q in _read_questions_cached():
        if q.get("id")==qid: return q
    return None

def admin_edit_list_ui():
    st.subheader("ערוך תוכן")
    all_q = _read_questions_cached()
    if not all_q:
        st.info("אין שאלות לעריכה")
        if st.button("חזרה"): st.session_state["admin_screen"] = "menu"; st.rerun()
        return
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
        st.error("השאלה לא נמצאה")
        st.session_state["admin_screen"] = "edit_list"
        return

    st.subheader("תצוגת שאלה ועריכה")
    _render_media(q, key=f"adm_{qid}")
    st.markdown(f"### {q['question']}")
    st.caption(f"קטגוריה: {q.get('category','')} | קושי: {q.get('difficulty','')}")

    col1, col2 = st.columns(2)
    ans = q["answers"]

    def chip(label: str, ok: bool):
        css = "badge-ok" if ok else "badge-err"
        st.markdown(f"<div class='{css}' style='margin-bottom:8px'>{html.escape(label)}</div>", unsafe_allow_html=True)

    with col1:
        for a in ans[::2]: chip(a["text"], a.get("is_correct", False))
    with col2:
        for a in ans[1::2]: chip(a["text"], a.get("is_correct", False))

    st.divider()
    colA, colB, colC, colD = st.columns(4)
    if colA.button("ערוך"):
        st.session_state["admin_edit_mode"] = True; st.rerun()

    if colB.button("חזרה"):
        st.session_state["admin_screen"] = "edit_list"
        st.session_state.pop("admin_edit_mode", None)
        st.rerun()

    if colC.button("שמור", disabled=not st.session_state.get("admin_edit_mode", False)):
        try:
            new_q = dict(q)
            new_q["question"]   = st.session_state.get("edit_q_text", q["question"])
            new_q["category"]   = st.session_state.get("edit_q_cat", q.get("category", ""))
            new_q["difficulty"] = st.session_state.get("edit_q_diff", q.get("difficulty", 2))

            correct_index_1based = st.session_state.get("edit_correct_idx", 1)
            ci = max(0, min(3, int(correct_index_1based) - 1))

            new_answers = []
            for i in range(4):
                txt = st.session_state.get(f"edit_ans_{i}", q["answers"][i]["text"])
                new_answers.append({"text": txt, "is_correct": (ci == i)})
            new_q["answers"] = new_answers

            new_q["type"] = st.session_state.get("edit_q_type", q.get("type", "text"))
            new_q["content_url"] = st.session_state.get("edit_q_media_url", q.get("content_url", ""))

            all_q = _read_questions_cached()
            for i, row in enumerate(all_q):
                if row.get("id") == qid:
                    all_q[i] = new_q
                    break
            _write_questions(all_q)
            st.session_state["admin_edit_mode"] = False
            flash("success", "עדכון בוצע בהצלחה")
            st.rerun()
        except Exception:
            flash("error", "שמירה נכשלה. בדוק הרשאות/חיבור ל-Supabase ונסה שוב.")
            st.rerun()

    if colD.button("רענן"):
        st.rerun()

    # -------- מצב עריכה --------
    if st.session_state.get("admin_edit_mode", False):
        st.markdown("### מצב עריכה")
        st.text_input("מלל השאלה", value=q["question"], key="edit_q_text")
        st.text_input("קטגוריה", value=q.get("category", ""), key="edit_q_cat")
        st.number_input("קושי", min_value=1, max_value=5, value=int(q.get("difficulty", 2)), key="edit_q_diff")

        st.markdown("**מדיה**")
        t = q.get("type", "text")
        st.selectbox("סוג", ["image","video","audio","text"],
                     index=["image","video","audio","text"].index(t), key="edit_q_type")

        # ודא key קיים
        if "edit_q_media_url" not in st.session_state:
            st.session_state["edit_q_media_url"] = q.get("content_url","")

        up = st.file_uploader(
            "החלף קובץ (תמונה/וידאו/אודיו)",
            type=["jpg","jpeg","png","gif","mp4","webm","m4a","mp3","wav","ogg","heic","heif"],
            key="edit_q_upload"
        )

        # מנגנון "פעם אחת"
        if up is None:
            st.session_state.pop("edit_upload_done", None)
        elif not st.session_state.get("edit_upload_done"):
            saved = _save_uploaded_to_storage(up)
            st.session_state["edit_q_media_url"] = saved
            st.session_state["edit_upload_done"] = True
            flash("success", "קובץ הוחלף בהצלחה")
            st.rerun()

        # שליטה בלעדית של הווידג'ט בערך
        st.text_input("URL / נתיב", key="edit_q_media_url")

        preview_url = _signed_or_raw(st.session_state.get("edit_q_media_url", ""), 300) \
                      if st.session_state.get("edit_q_media_url") else ""
        current_type = st.session_state.get("edit_q_type", t)
        if current_type == "image" and preview_url:
            st.image(preview_url, use_container_width=True)
        elif current_type == "video" and preview_url:
            st.markdown(
                f"""
                <div class="video-shell">
                  <video src="{html.escape(preview_url)}" muted playsinline controls preload="metadata"></video>
                  <a class="alt-link" href="{html.escape(preview_url)}" target="_blank" rel="noopener">
                    סרטון לא עובד? לחץ כאן
                  </a>
                </div>
                """,
                unsafe_allow_html=True
            )
        elif current_type == "audio" and preview_url:
            st.audio(preview_url)

def admin_delete_list_ui():
    st.subheader("מחק תוכן")
    all_q = _read_questions_cached()
    if not all_q:
        st.info("אין שאלות למחיקה")
        if st.button("חזרה"): st.session_state["admin_screen"]="menu"; st.rerun()
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
    if c1.button("מחק") and checked_ids:
        new_list = [x for x in all_q if x.get("id") not in checked_ids]
        _write_questions(new_list)
        st.session_state["admin_screen"]="menu"
        flash("success", "תוכן נמחק בהצלחה")
        st.rerun()
    if c2.button("רענן"): st.rerun()
    if c3.button("חזרה"): st.session_state["admin_screen"]="menu"; st.rerun()

def admin_add_form_ui():
    st.subheader("הוסף תוכן")
    t = st.selectbox("סוג", ["image","video","audio","text"], key="add_type")

    if "add_media_url" not in st.session_state:
        st.session_state["add_media_url"] = ""

    if t != "text":
        up = st.file_uploader(
            "הוסף קובץ (תמונה/וידאו/אודיו)",
            type=["jpg","jpeg","png","gif","mp4","webm","m4a","mp3","wav","ogg","heic","heif"],
            key="add_upload"
        )

        # מנגנון "פעם אחת"
        if up is None:
            st.session_state.pop("add_upload_done", None)
        elif not st.session_state.get("add_upload_done"):
            saved = _save_uploaded_to_storage(up)
            st.session_state["add_media_url"] = saved
            st.session_state["add_upload_done"] = True
            flash("success", "קובץ נשמר בהצלחה")
            st.rerun()

        st.text_input("או הדבק URL", key="add_media_url")

        signed = _signed_or_raw(st.session_state["add_media_url"], 300) if st.session_state["add_media_url"] else ""
        if signed:
            if t == "image":
                st.image(signed, use_container_width=True)
            elif t == "video":
                st.markdown(
                    f"""
                    <div class="video-shell">
                      <video src="{html.escape(signed)}" muted playsinline controls preload="metadata"></video>
                      <a class="alt-link" href="{html.escape(signed)}" target="_blank" rel="noopener">
                        סרטון לא עובד? לחץ כאן
                      </a>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            elif t == "audio":
                st.audio(signed)

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
    if st.button("שמור ועדכן"):
        if not q_text or any(not x for x in a_vals):
            flash("warning", "חובה למלא שאלה ו-4 תשובות"); st.rerun()
        elif t!="text" and not st.session_state.get("add_media_url"):
            flash("warning", "לשאלת מדיה חובה לצרף קובץ או URL"); st.rerun()
        else:
            try:
                all_q = _read_questions_cached()
                new_item = {
                    "id": uuid.uuid4().hex,
                    "type": t,
                    "content_url": st.session_state.get("add_media_url","") if t!="text" else "",
                    "question": q_text,
                    "answers": [{"text": a_vals[i], "is_correct": (i+1)==correct_idx_1based} for i in range(4)],
                    "category": category,
                    "difficulty": difficulty,
                    "created_at": datetime.utcnow().isoformat()
                }
                all_q.append(new_item)
                _write_questions(all_q)
                st.session_state["admin_screen"]="menu"
                flash("success", "תוכן נוסף בהצלחה")
                st.rerun()
            except Exception:
                flash("error", "שמירה נכשלה. בדוק הרשאות/חיבור ל-Supabase ונסה שוב.")
                st.rerun()

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
