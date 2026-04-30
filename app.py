# app.py
import streamlit as st
import json
import re
import os
import io
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from PyPDF2 import PdfReader
from docx import Document
import math
import pandas as pd

# ============================================================
# 기본 설정 및 로거
# ============================================================
st.set_page_config(page_title="AI 영어 마스터", page_icon="🎓", layout="wide")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_english_master")

# ============================================================
# 보안 및 시크릿 확인
# ============================================================
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    APP_PASSWORD = st.secrets["APP_PASSWORD"]
except Exception as e:
    st.error("🚨 보안 설정(Secrets)이 완료되지 않았습니다. 관리자에게 문의하세요.")
    logger.exception("Missing secrets")
    st.stop()

DB_FILE = "my_english_docs.json"

# ============================================================
# 파일 기반 DB 유틸리티 (간단한 JSON 저장소)
# ============================================================
def load_library() -> Dict[str, Any]:
    if not os.path.exists(DB_FILE):
        return {}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            if not content:
                return {}
            return json.loads(content)
    except Exception as e:
        logger.exception("Failed to load library")
        return {}

def save_to_library(title: str, text: str) -> None:
    data = load_library()
    data[title] = {
        "text": text,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def delete_from_library(title: str) -> None:
    data = load_library()
    if title in data:
        del data[title]
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

# ============================================================
# LLM 래퍼: Gemini 호출을 중앙에서 관리 (재시도, 타임아웃, 파싱)
# ============================================================
# NOTE: google.genai 클라이언트는 환경에 따라 설치/버전 차이가 있으니
# 실제 배포 환경에서 genai 패키지 문서를 확인하세요.
try:
    from google import genai
except Exception:
    genai = None
    logger.warning("google.genai import failed. Ensure genai SDK is installed in the environment.")

class LLMClient:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model
        self.client = None
        if genai:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception:
                logger.exception("Failed to initialize genai.Client")
                self.client = None

    def call_llm(self, prompt: str, max_retries: int = 2, retry_delay: float = 1.0, timeout: float = 30.0) -> str:
        """
        중앙 LLM 호출 함수: 재시도, 예외 처리, 기본 타임아웃(내부 SDK가 지원하면 사용)
        반환: raw text (str)
        """
        if not self.client:
            raise RuntimeError("LLM client not initialized")

        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                # genai SDK 호출 (동기)
                # SDK의 실제 파라미터는 버전에 따라 다를 수 있으니 필요시 조정하세요.
                response = self.client.models.generate_content(model=self.model, contents=prompt)
                text = getattr(response, "text", None)
                if text is None:
                    # 일부 SDK는 response.output[0].content 등 다른 구조를 가질 수 있음
                    text = str(response)
                return text
            except Exception as e:
                last_exc = e
                logger.warning("LLM call failed (attempt %s): %s", attempt + 1, str(e))
                time.sleep(retry_delay * (attempt + 1))
        logger.exception("LLM call failed after retries")
        raise last_exc

    @staticmethod
    def extract_json_from_text(text: str) -> Optional[Dict]:
        """
        AI가 반환한 텍스트에서 JSON 객체를 안전하게 추출
        """
        if not text:
            return None
        # 먼저 ```json 블록 제거
        clean = text.replace("```json", "").replace("```", "").strip()
        # 가장 큰 중괄호 블록을 찾음
        matches = re.findall(r'\{(?:[^{}]|(?R))*\}', clean, re.DOTALL)
        if not matches:
            # fallback: find first { ... } via simple regex
            m = re.search(r'\{.*\}', clean, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    return None
            return None
        # choose the longest match (likely the full JSON)
        longest = max(matches, key=len)
        try:
            return json.loads(longest)
        except Exception:
            # 마지막 시도: replace single quotes -> double quotes (risky)
            try:
                alt = longest.replace("'", '"')
                return json.loads(alt)
            except Exception:
                return None

# ============================================================
# 영어 튜터 엔진 (기존 기능을 안정적으로 래핑)
# ============================================================
class EnglishTutorEngine:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def bulk_translate(self, sentences: List[str]) -> List[str]:
        if not sentences:
            return []
        dict_sentences = {str(i): s for i, s in enumerate(sentences)}
        prompt = (
            "당신은 1:1 직독직해 전문 번역기입니다. 아래 JSON의 번호를 유지하며 영어 문장을 한국어로 번역하세요.\n"
            f"입력 데이터: {json.dumps(dict_sentences, ensure_ascii=False)}\n"
            "출력은 반드시 JSON 형식으로, 키는 입력과 동일한 숫자 문자열로 유지하세요."
        )
        try:
            raw = self.llm.call_llm(prompt)
            parsed = self.llm.extract_json_from_text(raw)
            if parsed is None:
                logger.warning("bulk_translate: JSON 파싱 실패, 원문 반환 시도")
                # fallback: line-by-line naive translation placeholder
                return ["번역 실패: AI 응답 파싱 불가"] * len(sentences)
            # build list in order
            result = [parsed.get(str(i), "번역 누락") for i in range(len(sentences))]
            return result
        except Exception as e:
            logger.exception("bulk_translate error")
            return [f"🚨 서버 통신 에러: {str(e)}"] * len(sentences)

    def deep_analyze(self, text: str) -> Dict[str, Any]:
        prompt = (
            "당신은 초고속 영어 강사입니다. 아래 문장을 분석하여 순수 JSON으로 응답하세요. 단일 텍스트 문자열(String)로만 작성하세요.\n"
            '{\n'
            '  "grammar": "문법 강의 및 형식",\n'
            '  "examples": "비슷한 예시 2~3개와 해석",\n'
            '  "background": "주요 단어 뜻, 자연스러운 한글 발음"\n'
            '}\n'
            f'문장: "{text}"\n'
            "출력은 반드시 JSON 객체 하나로만 응답하세요."
        )
        try:
            raw = self.llm.call_llm(prompt)
            parsed = self.llm.extract_json_from_text(raw)
            if parsed is None:
                logger.warning("deep_analyze: JSON 파싱 실패")
                return {"grammar": "파싱 실패", "examples": "파싱 실패", "background": "파싱 실패"}
            return parsed
        except Exception as e:
            logger.exception("deep_analyze error")
            return {"grammar": "에러", "examples": "에러", "background": f"🚨 상세 에러: {str(e)}"}

    def get_pattern_study(self, pattern_text: str) -> Dict[str, Any]:
        prompt = (
            f"당신은 영어 전문가입니다. 패턴 '{pattern_text}'에 대한 설명과 실전 예문 10개를 순수 JSON으로 작성하세요.\n"
            '{\n'
            '  "explanation": "이 패턴의 뉘앙스 설명",\n'
            '  "examples": ["1. 영어 - 한국어", "2. 영어 - 한국어", "3. 영어 - 한국어", "4. 영어 - 한국어", "5. 영어 - 한국어", "6. 영어 - 한국어", "7. 영어 - 한국어", "8. 영어 - 한국어", "9. 영어 - 한국어", "10. 영어 - 한국어"]\n'
            '}\n'
            "출력은 반드시 JSON 객체 하나로만 응답하세요."
        )
        try:
            raw = self.llm.call_llm(prompt)
            parsed = self.llm.extract_json_from_text(raw)
            if parsed is None:
                logger.warning("get_pattern_study: JSON 파싱 실패")
                return {"explanation": "형식 이탈", "examples": []}
            return parsed
        except Exception as e:
            logger.exception("get_pattern_study error")
            return {"explanation": f"🚨 통신 에러: {str(e)}", "examples": []}

    def extract_text(self, uploaded_file) -> str:
        text = ""
        try:
            file_type = uploaded_file.name.split('.')[-1].lower()
            if file_type == 'pdf':
                pdf_reader = PdfReader(uploaded_file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + " "
            elif file_type == 'docx':
                # docx: read bytes safely
                uploaded_file.seek(0)
                doc = Document(io.BytesIO(uploaded_file.read()))
                for para in doc.paragraphs:
                    if para.text:
                        text += para.text + " "
            else:
                # fallback: try reading as text
                uploaded_file.seek(0)
                try:
                    text = uploaded_file.read().decode('utf-8')
                except Exception:
                    text = ""
        except Exception as e:
            logger.exception("extract_text error")
            return ""
        return text.strip()

    def split_into_sentences(self, text: str) -> List[str]:
        if not text:
            return []
        # 간단한 문장 분리: 마침표/물음표/느낌표 기준 + 줄바꿈 제거
        sentences = re.split(r'(?<=[.!?])\s+', text.replace('\r', ' ').replace('\n', ' '))
        cleaned = [s.strip() for s in sentences if len(s.strip()) > 5]
        return cleaned

# ============================================================
# 150 패턴 데이터 (변경 없음, 캐시 적용)
# ============================================================
@st.cache_data
def get_unique_150_patterns() -> List[str]:
    patterns = [
        "I am ~ (나는 ~상태야)", "I'm getting ~ (나는 점점 ~해지고 있어)", "I'm trying to ~ (나는 ~하려고 노력 중이야)",
        "I'm looking forward to ~ (나는 ~이 너무 기대돼)", "I'm planning to ~ (나는 ~할 계획이야)", "I'm worried about ~ (나는 ~가 걱정돼)",
        "I'm thinking of ~ (나는 ~할까 생각 중이야)", "I'm used to ~ (나는 ~에 익숙해)", "I'm supposed to ~ (나는 ~하기로 되어 있어)",
        "I'm ready to ~ (나는 ~할 준비가 됐어)", "Do you ~? (너는 ~하니?)", "Do you know ~? (너는 ~을 아니?)",
        "Do you want me to ~? (내가 ~해주길 바라니?)", "Do you mind if I ~? (내가 ~해도 괜찮을까?)", "Do you happen to know ~? (혹시 ~아세요?)",
        "Do you have any ~? (~가 좀 있나요?)", "Do you feel like ~ing? (~하고 싶은 기분이야?)", "Don't you ~? (너 ~하지 않니?)",
        "Don't forget to ~ (~하는 거 잊지 마)", "Don't tell me ~ (설마 ~라는 건 아니겠지)", "Are you ~? (너는 ~니?)",
        "Are you sure ~? (정말 ~인 게 확실해?)", "Are you going to ~? (너 ~할 거야?)", "Are you done with ~? (~는 다 끝났어?)",
        "Are you ready to ~? (~할 준비 다 됐어?)", "Have you ~? (너 ~해봤어? / ~했어?)", "Have you ever ~? (너 살면서 ~해본 적 있어?)",
        "Have you decided ~? (~할지 결정했어?)", "Haven't you ~? (너 ~하지 않았어?)", "I have ~ (나는 ~을 가지고 있어/경험했어)",
        "I have to ~ (나는 ~해야만 해)", "I've got to ~ (나 진짜 ~해야 돼)", "I don't have to ~ (나는 ~할 필요가 없어)",
        "I have no choice but to ~ (나는 ~할 수밖에 없어)", "I have a feeling that ~ (왠지 ~일 것 같은 예감이 들어)", 
        "I have nothing to do with ~ (나는 ~와 아무 상관이 없어)", "Can I ~? (제가 ~해도 될까요?)", "Can you ~? (너 ~해줄 수 있어?)",
        "Can you tell me ~? (~에 대해 말해줄래?)", "Can't you ~? (너 ~할 수 없어?)", "Could you ~? (~해주실 수 있나요? - 정중)",
        "Could I ~? (제가 ~해도 될까요? - 정중)", "I can't ~ (나는 ~할 수 없어)", "I can't believe ~ (나는 ~라는 걸 믿을 수가 없어)",
        "I can't stand ~ (나는 ~을 참을 수가 없어)", "I can't wait to ~ (빨리 ~하고 싶어 미치겠어)", "I can't afford to ~ (나는 ~할 여유/돈이 없어)",
        "I can't help ~ing (나는 ~하지 않을 수 없어)", "You can't ~ (너는 ~하면 안 돼)", "Will you ~? (너 ~해줄래?)",
        "I will ~ (나는 ~할 거야)", "I won't ~ (나는 절대 ~하지 않을 거야)", "I would like to ~ (저는 ~하고 싶습니다)",
        "I would rather ~ (나는 차라리 ~할래)", "Would you like to ~? (~하시겠어요?)", "Would you mind ~ing? (~해주시면 감사하겠습니다)",
        "I should ~ (나는 ~해야 해/하는 게 좋아)", "You should ~ (너는 ~하는 게 좋겠어)", "Should I ~? (제가 ~해야 할까요?)", 
        "I shouldn't have ~ (내가 ~하지 말았어야 했는데)", "Let me ~ (내가 ~할게/해볼게)", "Let me know ~ (나에게 ~을 알려줘)", 
        "Let's ~ (우리 ~하자)", "Let's not ~ (우리 ~하지 말자)", "Why don't you ~? (너 ~하는 게 어때?)", 
        "Why don't we ~? (우리 ~하는 게 어때?)", "Why did you ~? (너 대체 왜 ~한 거야?)", "Why are you ~? (너 왜 ~하고 있어?)", 
        "How about ~? (~는 어때?)", "How come ~? (어째서 ~인 거야?)", "How often ~? (얼마나 자주 ~해?)", 
        "How long does it take to ~? (~하는 데 얼마나 걸려?)", "How many ~? (~가 몇 개나 있어?)", "How much ~? (~가 얼마나 있어/얼마야?)", 
        "What do you ~? (너는 무엇을 ~해?)", "What are you ~ing? (너 무슨 ~하고 있어?)", "What if ~? (만약 ~라면 어쩌지?)", 
        "What makes you ~? (무엇이 널 ~하게 만들었어?)", "What I mean is ~ (내 말뜻은 ~라는 거야)", "What's wrong with ~? (~에 무슨 문제 있어?)", 
        "When do you ~? (너는 언제 ~해?)", "When did you ~? (너 언제 ~했어?)", "When is a good time to ~? (~하기 언제가 좋아?)", 
        "Where do you ~? (너는 어디서 ~해?)", "Where did you ~? (너 어디서 ~했어?)", "Where can I ~? (어디서 ~할 수 있을까요?)", 
        "Who is ~? (누가 ~야?)", "Who do you ~? (너는 누구를 ~해?)", "Who wants to ~? (누가 ~하고 싶어?)", 
        "Is it okay if ~? (~해도 괜찮을까요?)", "Is there ~? (~가 있나요?)", "Is it possible to ~? (~하는 게 가능할까요?)", 
        "It is ~ (그건 ~야)", "It is time to ~ (~할 시간이야)", "It looks like ~ (~인 것 같아 보여)", 
        "It seems that ~ (~인 모양이야)", "It takes ~ (~가 필요해/걸려)", "It doesn't matter ~ (~는 상관없어)", 
        "It's hard to ~ (~하기가 힘들어)", "It's worth ~ing (~할 가치가 있어)", "There is ~ (~가 있어)", 
        "There are ~ (~들이 있어)", "There is no need to ~ (~할 필요가 전혀 없어)", "There is nothing ~ (~한 게 아무것도 없어)", 
        "I think ~ (내 생각엔 ~야)", "I don't think ~ (나는 ~라고 생각하지 않아)", "Do you think ~? (너는 ~라고 생각해?)", 
        "What do you think of ~? (~에 대해 어떻게 생각해?)", "I thought ~ (나는 ~라고 생각했었어)", "I didn't mean to ~ (내가 ~할 의도는 아니었어)", 
        "I wonder if ~ (~인지 아닌지 궁금해)", "I was wondering if ~ (혹시 ~인지 궁금했어요)", "I need to ~ (나는 ~할 필요가 있어)", 
        "You need to ~ (너는 ~해야만 해)", "All you need to do is ~ (네가 해야 할 일은 ~뿐이야)", "I want to ~ (나는 ~하고 싶어)", 
        "I don't want to ~ (나는 ~하기 싫어)", "I just wanted to ~ (나는 단지 ~하고 싶었을 뿐이야)", "You'd better ~ (너는 ~하는 게 좋을걸)", 
        "You'd better not ~ (너는 ~하지 않는 게 좋을걸)", "Make sure to ~ (반드시 ~하도록 해)", "Be sure to ~ (꼭 ~하도록 해)", 
        "Feel free to ~ (부담 갖지 말고 편하게 ~해)", "Be careful not to ~ (~하지 않도록 조심해)", "I promise to ~ (내가 ~할게 약속해)", 
        "I swear ~ (맹세컨대 ~야)", "I hope ~ (나는 ~하길 바라)", "I wish I could ~ (내가 ~할 수 있다면 참 좋을 텐데)", 
        "I'm afraid ~ (유감이지만 ~인 것 같아)", "I'm sorry to ~ (~해서 미안해)", "Thank you for ~ (~해줘서 고마워)", 
        "Thanks to ~ (~덕분에)", "No wonder ~ (어쩐지 ~하더라)", "No matter what ~ (무슨 일이 있어도)", 
        "As far as I know ~ (내가 아는 한은)", "As long as ~ (~하는 한은)", "Even if ~ (설령 ~일지라도)", 
        "Even though ~ (비록 ~일지라도)", "By the way ~ (그건 그렇고)", "Speaking of ~ (~얘기가 나와서 말인데)", 
        "Instead of ~ (~하는 대신에)", "In case ~ (만약 ~할 경우를 대비해서)", "Because of ~ (~때문에)", 
        "Due to ~ (~로 인하여)", "According to ~ (~에 따르면)", "As a result ~ (그 결과로)", 
        "For example ~ (예를 들면)", "In fact ~ (사실은)", "To be honest ~ (솔직히 말하자면)", "Believe it or not ~ (믿든 안 믿든 간에)"
    ]
    return [f"Day {i+1:03d} : {p}" for i, p in enumerate(patterns)]

# ============================================================
# 세션 초기화 및 UI 메인
# ============================================================
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 나만의 영어 서재 (보안 접속)")
    pwd = st.text_input("접속 비밀번호를 입력하세요:", type="password")
    if st.button("접속하기"):
        if pwd == str(APP_PASSWORD):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")
    st.stop()

if 'study_log' not in st.session_state: st.session_state.study_log = []
if 'all_sentences' not in st.session_state: st.session_state.all_sentences = []
if 'current_text' not in st.session_state: st.session_state.current_text = ""
if 'current_page' not in st.session_state: st.session_state.current_page = 0
if 'page_translations' not in st.session_state: st.session_state.page_translations = {}

# LLM 클라이언트 및 튜터 엔진 초기화
llm_client = LLMClient(api_key=GEMINI_API_KEY, model="gemini-2.5-flash")
tutor = EnglishTutorEngine(llm_client)

# ---------------- Sidebar: Library ----------------
with st.sidebar:
    st.header("📚 나만의 서재")
    st.write("저장된 문서를 불러오세요.")
    library = load_library()
    if library:
        saved_titles = list(library.keys())
        selected_doc = st.selectbox("저장된 문서 목록", ["선택하세요"] + saved_titles)
        col_load, col_del = st.columns(2)
        with col_load:
            if st.button("📂 불러오기", use_container_width=True) and selected_doc != "선택하세요":
                st.session_state.current_text = library[selected_doc]['text']
                st.session_state.all_sentences = tutor.split_into_sentences(st.session_state.current_text)
                st.session_state.current_page = 0
                st.session_state.page_translations = {}
                st.rerun()
        with col_del:
            if st.button("🗑️ 삭제", use_container_width=True) and selected_doc != "선택하세요":
                delete_from_library(selected_doc)
                st.success("삭제되었습니다.")
                st.rerun()
    else:
        st.info("아직 저장된 문서가 없습니다.")

st.title("🎓 AI 영어 전문가 마스터 시스템")
tabs = st.tabs(["🔍 스마트 문서 분석", "🧩 150 핵심 패턴", "📅 학습 일정 관리"])

# ---------------- Tab 1: Document Analysis ----------------
with tabs[0]:
    st.subheader("새 문서 업로드 및 분석")
    mode = st.radio("입력 방식", ["파일 첨부", "텍스트 직접 입력"], horizontal=True)
    temp_text = ""
    if mode == "파일 첨부":
        file = st.file_uploader("파일을 올려주세요 (PDF, DOCX)", type=["pdf", "docx"])
        if file:
            with st.spinner("파일을 추출 중입니다..."):
                temp_text = tutor.extract_text(file)
                if not temp_text:
                    st.warning("파일에서 텍스트를 추출하지 못했습니다. 다른 파일을 시도해 주세요.")
    else:
        temp_text = st.text_area("영어 문장을 붙여넣으세요", height=100)

    if temp_text:
        col_apply, col_save, _ = st.columns([2, 2, 6])
        with col_apply:
            if st.button("🚀 이 문서 분석 시작", type="primary"):
                st.session_state.current_text = temp_text
                st.session_state.all_sentences = tutor.split_into_sentences(temp_text)
                st.session_state.current_page = 0
                st.session_state.page_translations = {}
                st.rerun()
        with col_save:
            with st.popover("💾 서재에 저장하기"):
                doc_title = st.text_input("문서 제목을 입력하세요:")
                if st.button("저장 확정"):
                    if doc_title:
                        save_to_library(doc_title, temp_text)
                        st.success("사이드바의 서재에 저장되었습니다!")
                        st.rerun()
                    else:
                        st.error("제목을 입력해야 합니다.")

    st.divider()

    if st.session_state.all_sentences:
        page_size = 10
        total_pages = math.ceil(len(st.session_state.all_sentences) / page_size)
        current_page = st.session_state.current_page
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, len(st.session_state.all_sentences))
        current_chunk = st.session_state.all_sentences[start_idx:end_idx]

        if current_page not in st.session_state.page_translations:
            with st.spinner("AI가 1:1 직독직해 중입니다..."):
                st.session_state.page_translations[current_page] = tutor.bulk_translate(current_chunk)

        translations = st.session_state.page_translations[current_page]

        df = pd.DataFrame({
            "No.": range(start_idx + 1, end_idx + 1),
            "English (원문)": current_chunk,
            "Korean (직관적 해석)": translations[:len(current_chunk)]
        })
        df.set_index("No.", inplace=True)

        st.write("### 📖 병렬 학습 리스트 (줄을 클릭하면 분석이 나옵니다)")
        selection = st.dataframe(
            df,
            column_config={
                "English (원문)": st.column_config.TextColumn(width="large"),
                "Korean (직관적 해석)": st.column_config.TextColumn(width="large")
            },
            width="stretch", on_select="rerun", selection_mode="single-row"
        )

        col_prev, col_info, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("◀ 이전") and current_page > 0:
                st.session_state.current_page -= 1
                st.rerun()
        with col_info:
            st.markdown(f"<div style='text-align:center;'><b>{current_page+1} / {total_pages} 페이지</b></div>", unsafe_allow_html=True)
        with col_next:
            if st.button("다음 ▶") and current_page < total_pages - 1:
                st.session_state.current_page += 1
                st.rerun()

        def dict_to_text(data):
            if isinstance(data, dict):
                return "\n\n".join([f"- **{k}**: {v}" for k, v in data.items()])
            return str(data).replace("\\n", "\n")

        selected_rows = selection.get("selection", {}).get("rows", [])
        if selected_rows:
            target_s = current_chunk[selected_rows[0]]
            st.divider()
            st.markdown(f"### 🕵️‍♂️ 심층 리포트")
            st.info(f"**📖 원문:** {target_s}\n\n**💡 해석:** {translations[selected_rows[0]]}")

            with st.spinner("초고속 분석 중..."):
                analysis = tutor.deep_analyze(target_s)
                c1, c2, c3 = st.columns(3)
                c1.success(f"📐 **문법 & 형식**\n\n{dict_to_text(analysis.get('grammar'))}")
                c2.warning(f"💡 **응용 예시**\n\n{dict_to_text(analysis.get('examples'))}")
                c3.error(f"🌍 **배경 & 발음 & 단어**\n\n{dict_to_text(analysis.get('background'))}")

# ---------------- Tab 2: 150 Patterns ----------------
with tabs[1]:
    st.subheader("🚀 150 핵심 패턴 정복")
    all_patterns = get_unique_150_patterns()
    with st.container(height=350):
        selected_p = st.radio("패턴 리스트", all_patterns, label_visibility="collapsed")

    if st.button("이 패턴 집중 공략하기 🚀"):
        with st.spinner("AI가 10개의 맞춤 예문을 생성 중입니다..."):
            p_data = tutor.get_pattern_study(selected_p)
            st.session_state.p_study = p_data
            st.session_state.p_title = selected_p

    if 'p_study' in st.session_state:
        st.markdown(f"### 💡 {st.session_state.p_title}")
        st.info(st.session_state.p_study.get("explanation", "설명 데이터를 불러오지 못했습니다."))
        st.write("#### ✍️ 실전 예문 10선")
        for ex in st.session_state.p_study.get("examples", []):
            st.write(f"- {ex}")

        st.divider()
        if st.checkbox("✅ 오늘 이 패턴 마스터!"):
            st.balloons()
            if st.button("학습 달력에 도장 찍기"):
                st.session_state.study_log.append({"날짜": datetime.now().strftime("%Y-%m-%d %H:%M"), "유형": "패턴 집중 학습", "내용": st.session_state.p_title})
                st.success("달력에 저장되었습니다!")

# ---------------- Tab 3: Study Log ----------------
with tabs[2]:
    st.subheader("📅 나의 학습 히스토리")
    if st.session_state.study_log:
        st.table(pd.DataFrame(st.session_state.study_log).sort_values("날짜", ascending=False))
    else:
        st.write("아직 학습 기록이 없습니다.")
