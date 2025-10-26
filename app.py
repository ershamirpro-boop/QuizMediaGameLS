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

ADMIN_CODE = os.getenv("ADMIN_CODE", "admin246")  # אפשר להגדיר בסיקרטס
FIXED_N_QUESTIONS = 15

# Supabase (חינמי) - דרך Secrets
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
    """יצירת לקוח supabase פעם אחת (lazy)"""
    global _supabase
    if _supabase is None and _supabase_on():
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _supabase

def _content_type_for(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"

def _upload_path_to_supabase(tmp_path: str, original_name: str) -> str:
    """
    supabase-py v2 קורא קובץ מדיסק; לכן כשיש לנו bytes—נכתוב לקובץ זמני ונעלה אותו.
    מחזיר sb://bucket/object-path
    """
    sb = _get_supabase(); assert sb is not None
    ext = pathlib.Path(original_name).suffix.lower()
    folder = datetime.utcnow().strftime("media/%Y/%m")
    object_path = f"{folder}/{uuid.uuid4().hex}{ext}"
    content_type = _content_type_for(original_name)

    # חשוב: "upsert" כמחרוזת כדי לא לגרום ל-TypeError על headers
    sb.storage.from_(SUPABASE_BUCKET).upload(
        object_path,
        file=tmp_path,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    return f"sb://{SUPABASE_BUCKET}/{object_path}"

def upload_to_supabase(file_bytes: bytes, original_name: str) -> str:
    """עטיפה נוחה להעלאת bytes ל-Supabase"""
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        return _upload_path_to_supabase(tmp_path, original_name)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

def sign_url_sb(sb_url: str, expires_seconds: int = 300) -> str:
    """הפקת כתובת חתומה לצפייה מדפדפן"""
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
    """שומר לקובץ מקומי או ל־Supabase בהתאם להגדרות, ומחזיר URL לוגי"""
    if _supabase_on():
        return upload_to_supabase(upload.getbuffer(), upload.name)
    return _save_uploaded_file_local(upload)

def _signed_or_raw(url: str, seconds: int = 300) -> str:
    """ב־sb:// נחזיר URL חתום; אחרת נחזיר את ה־URL כמו שהוא"""
    if url.startswith("sb://") and _supabase_on():
        return sign_url_sb(url, seconds)
    return url

# ========================= מאגר שאלות: ענן או מקומי =========================
def _sb_download_bytes(object_path: str) -> bytes:
    sb = _get_supabase(); assert sb is not None
    return sb.storage.from_(SUPABASE_BUCKET).download(object_path)

def _sb_upload_bytes(object_path: str, data: bytes, content_type: str = "application/json"):
    sb = _get_supabase(); assert sb is not None
    try:
        sb.storage.from_(SUPABASE_BUCKET).remove([object_path])
    except Exception:
        pass
    sb.storage.from_(SUPABASE_BUCKET).upload(
        object_path,
        data,
        file_options={"content-type": content_type, "upsert": "true"},
    )

def _read_questions() -> List[Dict[str, Any]]:
    """
    קריאת ה־JSON מהענן/מקומי. דואג לניקוי בסיסי:
    - חייב מפתח 'question'
    - 'answers' רשימה באורך 4
    """
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
        if (
            isinstance(q, dict)
            and "question" in q
            and "answers" in q
            and isinstance(q["answers"], list)
            and len(q["answers"]) == 4
        ):
            clean.append(q)
    return clean

def _write_questions(all_q: List[Dict[str, Any]]) -> None:
    payload = json.dumps(all_q, ensure_ascii=False, indent=2).encode("utf-8")
    if _supabase_on():
        _sb_upload_bytes(QUESTIONS_OBJECT_PATH, payload, "application/json; charset=utf-8")
    else:
        LOCAL_QUESTIONS_JSON.write_bytes(payload)

# ========================= עיצוב כללי + מובייל + לייטבוקס =========================
st.set_page_config(page_title=APP_TITLE, page_icon="🎯", layout="wide")
st.markdown("""
<style>
.stApp{direction:rtl}
.block-container{padding-top:10px;padding-bottom:16px;max-width:900px}
h1,h2,h3,h4{text-align:right;letter-spacing:.2px}
label,p,li,.stMarkdown{text-align:right}

/* כפתור התחל */
.start-btn>button{width:100%;padding:14px 16px;font-size:18px;border-radius:12px;background:#23C483!important;color:#fff!important;border:0!important}

/* תגיות תוצאה */
.badge-ok{background:#E8FFF3;border:1px solid #23C483;color:#0b7a56;padding:6px 10px;border-radius:10px;font-size:14px}
.badge-err{background:#FFF0F0;border:1px solid #F44336;color:#a02121;padding:6px 10px;border-radius:10px;font-size:14px}

/* תצוגת מדיה */
img{max-height:52vh;object-fit:contain}
.video-shell,.audio-shell{width:100%}
.video-shell video,.audio-shell audio{width:100%}

/* Lightbox */
.zoom-wrap{position:relative;display:inline-block;width:100%}
.zoom-btn{position:absolute;top:10px;left:10px;z-index:2;padding:6px 10px;font-size:14px;border-radius:10px;background:rgba(0,0,0,.55);color:#fff;border:1px solid rgba(255,255,255,.4);cursor:pointer}
.lightbox-overlay{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;z-index:9999}
.lightbox-overlay.show{display:flex}
.lightbox-content{max-width:96vw;max-height:92vh}
.lightbox-content img{width:100%;height:auto;object-fit:contain}
.lightbox-close{position:fixed;top:12px;right:12px;z-index:10000;background:rgba(0,0,0,.65);color:#fff;border:1px solid rgba(255,255,255,.4);padding:6px 10px;border-radius:10px;cursor:pointer;font-size:16px}

/* בר תחתון */
.bottom-bar{position:sticky;bottom:0;background:rgba(255,255,255,.94);backdrop-filter:blur(6px);padding:10px 8px;border-top:1px solid rgba(0,0,0,.08)}
@media (prefers-color-scheme: dark){.bottom-bar{background:rgba(17,24,39,.9);border-top:1px solid rgba(255,255,255,.08)}}
</style>
""", unsafe_allow_html=True)

# ========================= Utilities =========================
def reset_admin_state():
    for k in ["admin_mode","admin_screen","admin_edit_mode","admin_edit_qid","add_state"]:
        st.session_state.pop(k, None)

def reset_game_state():
    for k in ["phase","questions","answers_map","current_idx","score","finished","review_idx"]:
        st.session_state.pop(k, None)

def _pick_session_questions(all_q: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not all_q: return []
    k = min(FIXED_N_QUESTIONS, len(all_q))
    chosen = random.sample(all_q, k=k)
    for q in chosen:
        # ערבוב תשובות
        random.shuffle(q["answers"])
    return chosen

def ensure_game_loaded():
    if "questions" not in st.session_state:
        qs = _read_questions()
        st.session_state.questions = _pick_session_questions(qs)
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
  <<TAG> id="{element_id}" {controls} playsinline preload="auto"></<TAG>>
  <div style="display:flex;gap:8px;align-items:center;margin-top:8px;">
    <button id="{element_id}_play" style="padding:8px 12px;border-radius:10px;border:1px solid #ccc;cursor:pointer;">▶︎ נגן</button>
    <small id="{element_id}_status">מנגן אוטומטית 3 פעמים...</small>
  </div>
</div>
<script>
(function(){{
  const el=document.getElementById("{element_id}");
  const btn=document.getElementById("{element_id}_play");
  const stx=document.getElementById("{element_id}_status");
  if(!el||!btn) return;
  const src=document.createElement("source"); src.src="{html.escape(url)}"; el.appendChild(src);
  let autoPlaysLeft=3;
  function tryPlay(){{
    const p=el.play(); if(p&&p.catch) p.catch(()=>{{stx.textContent="לחץ נגן כדי להתחיל";}});
  }}
  el.addEventListener("ended",()=>{{
    if(autoPlaysLeft>0){{
      autoPlaysLeft-=1;
      if(autoPlaysLeft>0){{ tryPlay(); stx.textContent="ניגון אוטומטי... ("+autoPlaysLeft+" נשארו)"; }}
      else{{ stx.textContent="סיום אוטומטי. ניתן לנגן ידנית."; }}
    }}
  }});
  tryPlay();
  btn.addEventListener("click",()=>{{ tryPlay(); }});
}})();
</script>
""".replace("<TAG>", tag), unsafe_allow_html=True)

def _render_media(q: Dict[str, Any], key: str):
    t = q.get("type","text")
    url = q.get("content_url","")
    if not url: return
    signed = _signed_or_raw(url, seconds=300)
    if t=="image": _image_with_lightbox(signed, key)
    elif t=="video": _video_or_audio_with_autoplay(signed, "video", key)
    elif t=="audio": _video_or_audio_with_autoplay(signed, "audio", key)

# ========================= Header =========================
st.title("🎯 משחק טריוויה מדיה")
st.caption("משחק פתוח ואנונימי. מדיה נטענת באופן פרטי ומאובטח. אין שמירת זהות.")

# כפתור כניסת מנהלים
col_top_left, col_top_right = st.columns([3,1])
with col_top_right:
    if st.button("כניסת מנהלים", key="admin_entry"):
        st.session_state["admin_mode"] = True
        st.session_state["admin_screen"] = "login"
        st.rerun()

# אם לא במצב אדמין - ודא שאפסנו כל state של אדמין
if not st.session_state.get("admin_mode"):
    for k in ["admin_screen","admin_edit_mode","admin_edit_qid","add_state"]:
        st.session_state.pop(k, None)

# ========================= UI משתמש רגיל =========================
if not st.session_state.get("admin_mode"):
    all_q = _read_questions()
    if "phase" not in st.session_state: st.session_state.phase = "welcome"

    if st.session_state.phase == "welcome":
        st.subheader("ברוך הבא!")
        st.write("תיאור קצר של המשחק... אפשר לעדכן בהמשך.")
        st.markdown('<div class="start-btn">', unsafe_allow_html=True)
        if st.button("התחל לשחק"):
            if not all_q: st.warning("אין שאלות במאגר כרגע.")
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
            q = qlist[idx]

            _render_media(q, key=f"q{idx}")
            st.markdown(f"### {q['question']}")
            if q.get("category"):
                st.caption(f"קטגוריה: {q.get('category')} | קושי: {q.get('difficulty','לא צוין')}")

            options = [a["text"] for a in q["answers"]]
            picked = st.session_state.answers_map.get(idx)
            choice = st.radio(
                "בחירה", options=options,
                index=options.index(picked) if picked in options else None,
                label_visibility="collapsed",
                key=f"quiz_radio_{idx}",
            )
            if choice is not None:
                st.session_state.answers_map[idx] = choice

            st.markdown('<div class="bottom-bar">', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            if c1.button("שמור והבא ▶"):
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

        options = [a["text"] for a in q["answers"]]
        current_pick = st.session_state.answers_map.get(ridx)
        choice = st.radio(
            "בחר/י תשובה",
            options=options,
            index=options.index(current_pick) if current_pick in options else None,
            label_visibility="collapsed",
            key=f"rev_radio_{ridx}",
        )
        if choice is not None:
            st.session_state.answers_map[ridx] = choice

        cols = st.columns(2)
        with cols[0]:
            if st.button("← הקודמת", disabled=(ridx==0)):
                st.session_state.review_idx -= 1; st.rerun()
        with cols[1]:
            if st.button("הבאה →", disabled=(ridx==len(qlist)-1)):
                st.session_state.review_idx += 1; st.rerun()

        st.divider()
        c1, c2 = st.columns(2)
        if c1.button("בדוק אותי"):
            st.session_state.score = _calc_score(st.session_state.questions, st.session_state.answers_map)
            st.session_state.phase = "result"; st.rerun()
        if c2.button("↩ חזור"):
            st.session_state.phase = "quiz"; st.rerun()

    elif st.session_state.phase == "result":
        total = len(st.session_state.questions); score = st.session_state.score
        pct = int(round(100 * score / max(1,total)))
        st.subheader("תוצאה")
        st.markdown(f"<h1 style='font-size:48px;text-align:center;'>{pct}%</h1>", unsafe_allow_html=True)
        if pct == 100:
            st.success("כל הכבוד!"); st.balloons()
        elif pct >= 61:
            st.info("😊 יפה מאוד")
        else:
            st.warning("🫣 קורה לכולם, אולי ננסה שוב?")

        st.divider()
        st.markdown("### פירוט המבחן (מה סימנת ומה נכון)")

        for i, q in enumerate(st.session_state.questions, start=1):
            picked = st.session_state.answers_map.get(i-1)
            correct = next(a["text"] for a in q["answers"] if a.get("is_correct"))
            is_right = (picked == correct)

            st.markdown(f"**{i}. {q['question']}**")
            if q.get("content_url"):
                st.caption("תצוגת מדיה (חתומה לזמן קצר):")
                _render_media(q, key=f"res_{i}")

            st.markdown(
                f"<div class='badge-{'ok' if is_right else 'err'}' style='margin:6px 0;'>"
                f"{'✔ תשובה נכונה' if is_right else '✖ תשובה שגויה'}</div>",
                unsafe_allow_html=True
            )
            st.markdown(f"- מה סימנת: **{html.escape(picked) if picked else '—'}**")
            st.markdown(f"- מה נכון: **{html.escape(correct)}**")
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
    if cols[0].button("היכנס"):
        if code == ADMIN_CODE:
            st.session_state["admin_screen"] = "menu"
            st.session_state["is_admin"] = True
            st.success("ברוך הבא, מנהל")
            st.rerun()
        else:
            st.error("קוד שגוי")
    if cols[1].button("↩ חזור"):
        reset_admin_state(); st.rerun()

def admin_menu_ui():
    st.subheader("לוח מנהל")
    c1, c2, c3 = st.columns(3)
    if c1.button("הוסף תוכן"): st.session_state["admin_screen"] = "add_form"; st.rerun()
    if c2.button("ערוך תוכן"): st.session_state["admin_screen"] = "edit_list"; st.rerun()
    if c3.button("מחק תוכן"): st.session_state["admin_screen"] = "delete_list"; st.rerun()
    st.divider()
    if st.button("↩ יציאה מממשק מנהל"):
        reset_admin_state(); st.rerun()

def _get_question_by_id(qid: str) -> Optional[Dict[str,Any]]:
    for q in _read_questions():
        if q.get("id")==qid: return q
    return None

def admin_edit_list_ui():
    st.subheader("ערוך תוכן")
    all_q = _read_questions()
    if not all_q:
        st.info("אין שאלות לעריכה"); 
        if st.button("↩ חזור"): st.session_state["admin_screen"] = "menu"; st.rerun()
        return
    options = {f"{i+1}. {q['question'][:80]}": q["id"] for i,q in enumerate(all_q)}
    label = st.selectbox("בחר שאלה לעריכה", list(options.keys()))
    c1, c2 = st.columns(2)
    if c1.button("פתח"):
        st.session_state["admin_edit_qid"] = options[label]
        st.session_state["admin_screen"] = "edit_detail"; st.rerun()
    if c2.button("↩ חזור"):
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

    # --- מצב עריכה ---
    st.divider()
    if "admin_edit_mode" not in st.session_state:
        st.session_state.admin_edit_mode = False

    colA, colB, colC = st.columns(3)
    if colA.button("ערוך שינויים"):
        st.session_state["admin_edit_mode"] = True; st.rerun()
    if colB.button("שמור ועדכן שינויים", disabled=not st.session_state.get("admin_edit_mode", False)):
        new_q = dict(q)
        new_q["question"]   = st.session_state.get("edit_q_text", q["question"])
        new_q["category"]   = st.session_state.get("edit_q_cat", q.get("category",""))
        new_q["difficulty"] = st.session_state.get("edit_q_diff", q.get("difficulty",2))

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
    if colC.button("↩ חזור"):
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
        st.text_input("נתיב או URL נוכחי", value=q.get("content_url",""), key="edit_q_media_url")
        up = st.file_uploader("החלף קובץ", type=["jpg","jpeg","png","gif","mp4","webm","m4a","mp3","wav","ogg"], key="edit_q_upload")
        if up:
            saved = _save_uploaded_to_storage(up)
            st.session_state["edit_q_media_url"] = saved
            st.success(f"הוחלף לקובץ: {saved}")
        preview_url = _signed_or_raw(st.session_state.get("edit_q_media_url", q.get("content_url","")), 300)
        if st.session_state.get("edit_q_type", t) == "image" and preview_url:
            st.image(preview_url, use_container_width=True)
        elif st.session_state.get("edit_q_type", t) == "video" and preview_url:
            st.video(preview_url)
        elif st.session_state.get("edit_q_type", t) == "audio" and preview_url:
            st.audio(preview_url)

def admin_delete_list_ui():
    st.subheader("מחק תוכן")
    all_q = _read_questions()
    if not all_q:
        st.info("אין שאלות למחיקה")
        if st.button("↩ חזור"): st.session_state["admin_screen"]="menu"; st.rerun()
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
    c1, c2 = st.columns(2)
    if c1.button("מחק שאלות", disabled=not checked_ids):
        new_list = [x for x in all_q if x.get("id") not in checked_ids]
        _write_questions(new_list)
        st.success("נמחק ושמור")
        st.session_state["admin_screen"]="menu"; st.rerun()
    if c2.button("↩ חזור"):
        st.session_state["admin_screen"]="menu"; st.rerun()

def admin_add_form_ui():
    st.subheader("הוסף תוכן")

    # אתחול מצב טופס פעם אחת
    if "add_state" not in st.session_state:
        st.session_state.add_state = {
            "type": "image",
            "media_url": "",
            "media_url_text": "",
            "q_text": "",
            "answers": ["", "", "", ""],
            "correct_1based": 1,
            "category": "",
            "difficulty": 2,
        }
    S = st.session_state.add_state  # נוחות

    S["type"] = st.selectbox("סוג", ["image","video","audio","text"],
                             index=["image","video","audio","text"].index(S["type"]))

    # העלאת קובץ / URL רק למדיה
    if S["type"] != "text":
        up = st.file_uploader(
            "הוסף קובץ (≤ 2MB, ≤ 5s)",
            type=["jpg","jpeg","png","gif","mp4","webm","m4a","mp3","wav","ogg"],
            key="add_upload",
        )
        if up:
            try:
                saved = _save_uploaded_to_storage(up)
                # >>> אוטומטית מעדכן את שדה ה-URL
                S["media_url"] = saved
                S["media_url_text"] = saved
                st.success(f"קובץ נשמר: {saved}")
            except Exception as e:
                st.error(f"שגיאה בשמירת הקובץ: {e}")

        S["media_url_text"] = st.text_input("או הדבק URL (לא חובה)", value=S["media_url_text"])

        # תצוגה מקדימה
        preview_url = (S["media_url_text"] or S["media_url"]).strip()
        if preview_url:
            signed = _signed_or_raw(preview_url, 300)
            if S["type"] == "image": st.image(signed, use_container_width=True)
            elif S["type"] == "video": st.video(signed)
            elif S["type"] == "audio": st.audio(signed)

    # פרטי השאלה
    S["q_text"] = st.text_input("טקסט השאלה", value=S["q_text"])

    st.markdown("**תשובות**")
    cols = st.columns(4)
    for i, c in enumerate(cols):
        with c:
            S["answers"][i] = st.text_input(f"תשובה {i+1}", value=S["answers"][i], key=f"add_ans_{i}")

    S["correct_1based"] = st.radio("סמן נכונה", options=[1,2,3,4],
                                   index=S["correct_1based"]-1, horizontal=True, key="add_correct_idx")
    S["category"] = st.text_input("קטגוריה (אופציונלי)", value=S["category"])
    S["difficulty"] = st.number_input("קושי 1-5", min_value=1, max_value=5, value=int(S["difficulty"]))

    st.divider()
    left, right = st.columns(2)
    with left:
        if st.button("שמור ועדכן", type="primary"):
            if not S["q_text"] or any(not x for x in S["answers"]):
                st.error("חובה למלא שאלה ו-4 תשובות"); return

            resolved_media_url = ""
            if S["type"] != "text":
                resolved_media_url = (S["media_url_text"] or S["media_url"]).strip()
                if not resolved_media_url:
                    st.error("לשאלת מדיה חובה לצרף קובץ או URL"); return

            new_item = {
                "id": uuid.uuid4().hex,
                "type": S["type"],
                "content_url": resolved_media_url if S["type"] != "text" else "",
                "question": S["q_text"],
                "answers": [
                    {"text": S["answers"][i], "is_correct": (i+1) == S["correct_1based"]}
                    for i in range(4)
                ],
                "category": S["category"],
                "difficulty": S["difficulty"],
                "created_at": datetime.utcnow().isoformat()
            }
            all_q = _read_questions()
            all_q.append(new_item)
            _write_questions(all_q)
            st.success("נשמר למאגר")

            # איפוס נוח לשאלה הבאה
            st.session_state.add_state = {
                "type": S["type"], "media_url": "", "media_url_text": "",
                "q_text": "", "answers": ["","","",""], "correct_1based": 1,
                "category": S["category"], "difficulty": S["difficulty"]
            }

    with right:
        if st.button("↩ חזור"):
            st.session_state["admin_screen"] = "menu"
            st.rerun()

# ניהול ניווט אדמין - מוצג רק כשבאמת במצב אדמין
if st.session_state.get("admin_mode"):
    st.divider()
    screen = st.session_state.get("admin_screen","login")
    if screen == "login": admin_login_ui()
    elif screen == "menu": admin_menu_ui()
    elif screen == "edit_list": admin_edit_list_ui()
    elif screen == "edit_detail": admin_edit_detail_ui()
    elif screen == "delete_list": admin_delete_list_ui()
    elif screen == "add_form": admin_add_form_ui()
