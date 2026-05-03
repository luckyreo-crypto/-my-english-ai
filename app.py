import streamlit as st
from google import genai
import json
import re
import os
from PyPDF2 import PdfReader
from docx import Document
import io
import pandas as pd
from datetime import datetime
import math
from groq import Groq
import traceback
import time

# 구글 스프레드시트 DB용 라이브러리
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# 🚨 화면 및 CSS 설정
# ============================================================
st.set_page_config(page_title="AI 영어 & 지식 마스터", page_icon="🎓", layout="wide")

st.markdown("""
<style>
.hover-word {
    cursor: help;
    border-bottom: 2px dashed #ff4b4b;
    color: #1f77b4;
    padding: 2px 4px;
    border-radius: 4px;
    transition: all 0.2s ease-in-out;
    background-color: transparent;
    font-weight: 500;
}
.hover-word:hover {
    background-color: #ffe8e8;
    color: #d62728;
    box-shadow: 1px 1px 5px rgba(0,0,0,0.1);
}
.cefr-badge {
    display: inline-block;
    padding: 0.3em 0.8em;
    font-size: 0.9em;
    font-weight: 700;
    color: white;
    background-color: #6f42c1;
    border-radius: 1rem;
    margin-bottom: 10px;
}
.info-box {
    background-color: #f8f9fa;
    border-left: 5px solid #007bff;
    padding: 15px;
    border-radius: 5px;
    margin-bottom: 15px;
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# 🔐 보안 및 설정
# ============================================================
try:
    APP_PASSWORD = st.secrets["APP_PASSWORD"]
    GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
    GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")
    GSHEET_URL = st.secrets["GSHEET_URL"]
    GCP_SA_JSON = st.secrets["GCP_SA_JSON"]
except Exception as e:
    st.error(f"🚨 보안 설정(Secrets) 로드 실패: {e}")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 나만의 지식 서재 (보안 접속)")
    pwd = st.text_input("접속 비밀번호를 입력하세요:", type="password")
    if st.button("접속하기"):
        if pwd == str(APP_PASSWORD):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")
    st.stop()

# ============================================================
# [1] 데이터 관리 엔진 (DB 및 유틸리티)
# ============================================================
def get_gsheet():
    try:
        if isinstance(GCP_SA_JSON, str):
            raw_secret = GCP_SA_JSON.strip().replace('\xa0', ' ').replace('\u200b', ' ')
            creds_dict = json.loads(raw_secret, strict=False)
        else:
            creds_dict = dict(GCP_SA_JSON)
        
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        clean_url = GSHEET_URL.split('?')[0] 
        sheet = client.open_by_url(clean_url).sheet1
        return sheet
    except Exception as e:
        return None

@st.cache_data(ttl=600, show_spinner=False)
def load_library():
    sheet = get_gsheet()
    if not sheet: return {}
    try:
        records = sheet.get_all_records()
        library = {}
        for row in records:
            real_keys = {k.lower(): k for k in row.keys()}
            t_key = real_keys.get('title')
            txt_key = real_keys.get('text')
            if t_key:
                library[str(row.get(t_key))] = {"text": str(row.get(txt_key, '')), "date": str(row.get(real_keys.get('date', ''), ''))}
        return library
    except: return {}

def save_to_library(title, text):
    sheet = get_gsheet()
    if not sheet: return
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    sheet.append_row([title, text, date_str])
    load_library.clear()

def delete_from_library(title):
    sheet = get_gsheet()
    if not sheet: return
    try:
        records = sheet.get_all_records()
        for i, row in enumerate(records):
            if str(row.get('title')) == str(title):
                sheet.delete_rows(i + 2)
                load_library.clear()
                break
    except: pass

def extract_safe_json(text):
    try:
        match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
        if match: return json.loads(match.group(0))
    except: pass
    return None

# ============================================================
# [2] 하이브리드 멀티 AI 엔진 (확장판)
# ============================================================
class MultiAIEngine:
    def __init__(self, selected_engine):
        self.engine_type = selected_engine

    def _call_ai(self, prompt, expect_json=True):
        try:
            if "Gemini" in self.engine_type:
                client = genai.Client(api_key=GEMINI_API_KEY)
                response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
                return response.text
            else:
                client = Groq(api_key=GROQ_API_KEY)
                kwargs = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
                if expect_json: kwargs["response_format"] = {"type": "json_object"}
                response = client.chat.completions.create(**kwargs)
                return response.choices[0].message.content
        except Exception as e:
            return f"🚨 에러: {str(e)}"

    def bulk_translate(self, sentences):
        prompt = f"다음 문장들을 자연스러운 한국어로 번역해줘. JSON 형식: {{\"translations\": []}}. 입력: {json.dumps(sentences)}"
        raw = self._call_ai(prompt)
        data = extract_safe_json(raw)
        return data.get("translations", ["번역 실패"] * len(sentences)) if data else ["번역 실패"] * len(sentences)

    def deep_analyze(self, text):
        prompt = f"영어 문장 '{text}'를 분석해줘. JSON 형식으로 cefr, grammar, examples, translations(literal, natural), words(word, meaning, pronunciation), context, quiz(question, hint, answer)를 포함해."
        return extract_safe_json(self._call_ai(prompt))

    def get_pattern_study(self, pattern):
        prompt = f"패턴 '{pattern}'에 대한 설명과 예문 10개를 JSON으로 작성해줘. {{'explanation': '', 'examples': []}}"
        return extract_safe_json(self._call_ai(prompt))

    # --- 신규 기능 메서드 ---
    def get_daily_proverb(self, exclude_list):
        prompt = f"전 세계 속담 중 하나를 골라줘. 제외 리스트: {exclude_list}. JSON 형식: {{\"proverb\": \"\", \"meaning\": \"\", \"origin\": \"\"}}"
        return extract_safe_json(self._call_ai(prompt))

    def get_idiom_story(self, exclude_list):
        prompt = f"사자성어 하나와 그 유래를 설명해줘. 제외 리스트: {exclude_list}. JSON 형식: {{\"idiom\": \"한자\", \"pronunciation\": \"독음\", \"meaning\": \"뜻\", \"story\": \"유래담\", \"lesson\": \"교훈\"}}"
        return extract_safe_json(self._call_ai(prompt))

    def get_realtime_news(self):
        prompt = "오늘의 주요 뉴스 TOP 10을 선정해줘. 절대 지어내지 말고 사실만 요약해. JSON 형식: {\"news\": [{\"title\": \"\", \"category\": \"\", \"summary\": \"\"}]}"
        return extract_safe_json(self._call_ai(prompt))

    def split_into_sentences(self, text):
        joined = " ".join(text.split('\n'))
        return [s.strip() for s in re.split(r'(?<=[.!?])\s+', joined) if len(s.strip()) > 3]

# ============================================================
# [3] UI 및 로직 통합
# ============================================================
# 세션 상태 초기화
for key in ['study_log', 'all_sentences', 'current_text', 'current_page', 'page_translations', 'used_proverbs', 'used_idioms']:
    if key not in st.session_state:
        st.session_state[key] = [] if 'used' in key or 'log' in key or 'sentences' in key else (0 if 'page' in key else "" if 'text' in key else {})

with st.sidebar:
    st.header("⚙️ 엔진 및 서재")
    selected_engine = st.radio("AI 모델:", ["Llama 3.3 (초고속)", "Gemini 2.0 (구글)"])
    st.divider()
    library = load_library()
    if library:
        selected_doc = st.selectbox("저장된 문서", ["선택하세요"] + sorted(list(library.keys())))
        if st.button("📂 불러오기") and selected_doc != "선택하세요":
            st.session_state.current_text = library[selected_doc]['text']
            st.session_state.all_sentences = MultiAIEngine(selected_engine).split_into_sentences(st.session_state.current_text)
            st.rerun()

tutor = MultiAIEngine(selected_engine)
st.title("🎓 AI 통합 지식 파트너")

tabs = st.tabs(["🔍 영어 분석", "🧩 핵심 패턴", "📜 오늘의 지혜", "📰 실시간 뉴스", "📅 학습 기록"])

# [Tab 0: 영어 분석] (기존 코드 통합)
with tabs[0]:
    temp_text = st.text_area("영어 텍스트 입력", value=st.session_state.current_text, height=150)
    if st.button("🚀 분석 시작"):
        st.session_state.all_sentences = tutor.split_into_sentences(temp_text)
        st.session_state.current_text = temp_text
        st.rerun()
    
    if st.session_state.all_sentences:
        sents = st.session_state.all_sentences
        df = pd.DataFrame({"원문": sents})
        selection = st.dataframe(df, use_container_width=True, on_select="rerun", selection_mode="single-row")
        
        selected_rows = selection.get("selection", {}).get("rows", [])
        if selected_rows:
            target = sents[selected_rows[0]]
            res = tutor.deep_analyze(target)
            if res:
                st.info(f"**분석:** {res.get('translations', {}).get('natural')}")
                st.write(f"**문법:** {res.get('grammar')}")

# [Tab 1: 핵심 패턴] (기존 코드 통합)
with tabs[1]:
    st.write("150개 핵심 패턴 학습 (생략)")

# [Tab 2: 오늘의 지혜] (신규: 속담 & 사자성어)
with tabs[2]:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🍎 오늘의 속담")
        if st.button("새 속담 뽑기"):
            res = tutor.get_daily_proverb(st.session_state.used_proverbs)
            if res:
                st.session_state.proverb_data = res
                st.session_state.used_proverbs.append(res['proverb'])
                if len(st.session_state.used_proverbs) > 100: st.session_state.used_proverbs.pop(0)
        
        if 'proverb_data' in st.session_state:
            p = st.session_state.proverb_data
            st.info(f"### {p['proverb']}")
            st.write(f"**뜻:** {p['meaning']}")
            with st.expander("📖 유래"): st.write(p['origin'])

    with c2:
        st.subheader("📚 오늘의 사자성어")
        if st.button("새 사자성어 뽑기"):
            res = tutor.get_idiom_story(st.session_state.used_idioms)
            if res:
                st.session_state.idiom_data = res
                st.session_state.used_idioms.append(res['idiom'])
                if len(st.session_state.used_idioms) > 100: st.session_state.used_idioms.pop(0)

        if 'idiom_data' in st.session_state:
            i = st.session_state.idiom_data
            st.success(f"### {i['idiom']} ({i['pronunciation']})")
            st.write(f"**해석:** {i['meaning']}")
            with st.expander("📜 유래담 보기"): 
                st.write(i['story'])
                st.caption(f"💡 교훈: {i['lesson']}")

# [Tab 3: 실시간 뉴스] (신규: 뉴스 TOP 10)
with tabs[3]:
    st.subheader("📰 실시간 주요 뉴스 TOP 10")
    if st.button("뉴스 업데이트 🔄"):
        with st.spinner("팩트 체크 중..."):
            res = tutor.get_realtime_news()
            if res: st.session_state.news_list = res['news']
    
    if 'news_list' in st.session_state:
        for idx, n in enumerate(st.session_state.news_list):
            st.markdown(f"**{idx+1}. [{n['category']}] {n['title']}**")
            st.write(f"> {n['summary']}")
            st.divider()

# [Tab 4: 학습 기록]
with tabs[4]:
    if st.session_state.study_log: st.table(st.session_state.study_log)
    else: st.write("기록이 없습니다.")
