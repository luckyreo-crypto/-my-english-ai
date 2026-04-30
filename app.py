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

# ============================================================
# 🔐 보안 및 설정 (Streamlit Secrets 사용)
# ============================================================
# 서버의 Secrets 설정창에 입력한 키를 자동으로 가져옵니다.
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    APP_PASSWORD = st.secrets["APP_PASSWORD"]  # 앱 접속 비밀번호
except:
    st.error("보안 설정(Secrets)이 완료되지 않았습니다. 관리자에게 문의하세요.")
    st.stop()

# 🗄️ 데이터베이스 파일 (Cloud 환경에서는 세션으로 관리하거나 별도 DB가 필요하나, 일단 로컬 호환 유지)
DB_FILE = "my_english_docs.json"

# ============================================================
# [로그인 시스템] 보안을 위해 비밀번호 입력창을 먼저 띄움
# ============================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 보안 접속")
    pwd = st.text_input("비밀번호를 입력하세요:", type="password")
    if st.button("접속"):
        if pwd == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")
    st.stop()

# ============================================================
# [나머지 엔진 코드는 동일 (API 키 부분만 교체)]
# ============================================================
class EnglishTutorEngine:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)

    # (이후 bulk_translate, deep_analyze, extract_text 등 이전 코드와 동일...)
    def bulk_translate(self, sentences):
        if not sentences: return []
        dict_sentences = {str(i): s for i, s in enumerate(sentences)}
        prompt = f"당신은 1:1 직독직해 전문 번역기입니다. 아래 JSON의 번호를 유지하며 번역하세요: {json.dumps(dict_sentences)}"
        try:
            response = self.client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            clean_text = response.text.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_text, re.DOTALL)
            if match:
                result_dict = json.loads(match.group(0))
                return [result_dict.get(str(i), "번역 누락") for i in range(len(sentences))]
            return ["파싱 실패"] * len(sentences)
        except: return ["통신 에러"] * len(sentences)

    def deep_analyze(self, text):
        prompt = f"당신은 영어 일타 강사입니다. 아래 문장을 분석하여 grammar, examples, background 3항목의 JSON으로 답하세요: {text}"
        try:
            response = self.client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            clean_text = response.text.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_text, re.DOTALL)
            return json.loads(match.group(0)) if match else {}
        except: return {"grammar": "오류", "examples": "오류", "background": "오류"}

    def get_pattern_study(self, pattern_text):
        prompt = f"영어 패턴 '{pattern_text}'에 대해 설명과 예문 10개를 JSON으로 만드세요: explanation, examples"
        try:
            response = self.client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            clean_text = response.text.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_text, re.DOTALL)
            return json.loads(match.group(0)) if match else {}
        except: return {}

    def extract_text(self, uploaded_file):
        text = ""
        f_ext = uploaded_file.name.split('.')[-1].lower()
        if f_ext == 'pdf':
            pdf = PdfReader(uploaded_file)
            for page in pdf.pages: text += page.extract_text() + " "
        elif f_ext == 'docx':
            doc = Document(io.BytesIO(uploaded_file.read()))
            for para in doc.paragraphs: text += para.text + " "
        return text

    def split_into_sentences(self, text):
        return [s.strip() for s in re.split(r'(?<=[.!?]) +', text.strip().replace('\n', ' ')) if len(s.strip()) > 5]

# 데이터 관리 함수들
def load_library():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def save_to_library(title, text):
    data = load_library()
    data[title] = {"text": text, "date": datetime.now().strftime("%y-%m-%d %H:%M")}
    with open(DB_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

def delete_from_library(title):
    data = load_library()
    if title in data:
        del data[title]
        with open(DB_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

# 패턴 데이터
@st.cache_data
def get_unique_150_patterns():
    # (위 답변에서 드린 150개 리스트 내용이 여기에 들어갑니다. 생략하지만 코드는 동일하게 유지하세요)
    return [f"Day {i+1:03d} : Pattern Content" for i in range(150)] 

# --- UI 메인 ---
st.set_page_config(page_title="AI 영어 마스터", page_icon="🎓", layout="wide")

# (이후 UI 그리는 부분은 이전 코드와 동일하게 작성하시면 됩니다)
# 탭 구성, 사이드바 서재 등...