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
import textwrap # 🚨 [추가됨] 열쇠 재조립을 위한 파이썬 기본 부품

# 구글 스프레드시트 DB용 라이브러리
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# 🚨 화면 설정
# ============================================================
st.set_page_config(page_title="AI 영어 마스터", page_icon="🎓", layout="wide")

# ============================================================
# 🔐 보안 및 설정
# ============================================================
try:
    APP_PASSWORD = st.secrets["APP_PASSWORD"]
    GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
    GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")
    GSHEET_URL = st.secrets["GSHEET_URL"]
    GCP_SA_JSON = st.secrets["GCP_SA_JSON"]
except:
    st.error("🚨 보안 설정(Secrets)이 완료되지 않았습니다.")
    st.stop()

# ============================================================
# [로그인 시스템]
# ============================================================
if "authenticated" not in st.session_state:
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

# ============================================================
# [1] 데이터 관리 엔진 (🌟 궁극의 에러 해결 코드 탑재 🌟)
# ============================================================
def get_gsheet():
    """구글 시트와 연결하는 마스터 함수"""
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets']
        creds_dict = json.loads(GCP_SA_JSON)
        
        # 🚨 [궁극의 해결책] Streamlit이 찌그러뜨린 열쇠를 분해해서 완벽하게 재조립합니다!
        raw_key = creds_dict.get("private_key", "")
        # 1. 꼬여있는 머리(Header)와 꼬리(Footer)를 잘라냅니다.
        key_body = raw_key.replace("-----BEGIN PRIVATE KEY-----", "").replace("-----END PRIVATE KEY-----", "")
        # 2. 스트림릿이 섞어놓은 모든 공백과 줄바꿈 불순물을 완전히 제거합니다.
        key_body = key_body.replace("\\n", "").replace("\n", "").replace(" ", "").replace('"', '')
        # 3. 구글 암호키 표준 규격인 '64글자'씩 예쁘게 다시 자릅니다.
        formatted_body = "\n".join(textwrap.wrap(key_body, 64))
        # 4. 머리와 꼬리를 정상적인 줄바꿈과 함께 다시 붙여줍니다. (완벽한 복구!)
        perfect_key = f"-----BEGIN PRIVATE KEY-----\n{formatted_body}\n-----END PRIVATE KEY-----\n"
        
        creds_dict["private_key"] = perfect_key
        
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_url(GSHEET_URL).sheet1
        return sheet
    except Exception as e:
        st.error(f"🚨 DB 연결 에러: {e}")
        return None

def load_library():
    """DB에서 데이터 불러오기"""
    sheet = get_gsheet()
    if not sheet: return {}
    records = sheet.get_all_records()
    library = {}
    for row in records:
        if row.get('Title'):
            library[str(row['Title'])] = {
                "text": str(row.get('Text', '')), 
                "date": str(row.get('Date', ''))
            }
    return library

def save_to_library(title, text):
    """DB에 데이터 저장하기 (덮어쓰기 지원)"""
    sheet = get_gsheet()
    if not sheet: return
    records = sheet.get_all_records()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    row_idx = None
    for i, row in enumerate(records):
        if str(row.get('Title')) == str(title):
            row_idx = i + 2 # 헤더가 1번줄이므로 +2
            break

    if row_idx:
        sheet.update_cell(row_idx, 2, text)
        sheet.update_cell(row_idx, 3, date_str)
    else:
        sheet.append_row([title, text, date_str])

def delete_from_library(title):
    """DB에서 데이터 삭제하기"""
    sheet = get_gsheet()
    if not sheet: return
    records = sheet.get_all_records()
    for i, row in enumerate(records):
        if str(row.get('Title')) == str(title):
            sheet.delete_rows(i + 2)
            break

# ============================================================
# [2] 하이브리드 멀티 AI 엔진
# ============================================================
class MultiAIEngine:
    def __init__(self, selected_engine):
        self.engine_type = selected_engine

    def _call_ai(self, prompt):
        try:
            if self.engine_type == "Gemini 2.5 (구글/무료)":
                if not GEMINI_API_KEY: return "🚨 Gemini API 키가 없습니다."
                client = genai.Client(api_key=GEMINI_API_KEY)
                response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                return response.text

            elif self.engine_type == "Llama 3.1 (메타/초고속 무료)":
                if not GROQ_API_KEY: return "🚨 Groq API 키가 없습니다."
                client = Groq(api_key=GROQ_API_KEY)
                response = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3
                )
                return response.choices[0].message.content

        except Exception as e:
            return f"🚨 {self.engine_type} 서버 에러: {str(e)}"

    def bulk_translate(self, sentences):
        if not sentences: return []
        dict_sentences = {str(i): s for i, s in enumerate(sentences)}
        prompt = f"당신은 번역기입니다. 아래 JSON의 번호를 유지하며 영어 문장을 한국어로 번역해 순수 JSON으로 답하세요.\n{json.dumps(dict_sentences)}"
        
        raw_text = self._call_ai(prompt)
        if "🚨" in raw_text: return [raw_text] * len(sentences)
        
        clean_text = raw_text.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        if match: 
            result_dict = json.loads(match.group(0))
            return [result_dict.get(str(i), "번역 누락") for i in range(len(sentences))]
        return ["파싱 실패 (AI 응답 오류)"] * len(sentences)

    def deep_analyze(self, text):
        prompt = f"""
        당신은 대한민국 최고의 영어 일타 강사입니다. 아래 문장을 깊이 있게 분석하여 반드시 순수 JSON으로만 응답하세요.
        {{
            "grammar": "문장의 구조(1~5형식 중 무엇인지)와 핵심 문법 요소에 대한 아주 상세하고 친절한 설명",
            "examples": [
                "1. 예문 - 해석",
                "2. 예문 - 해석",
                "3. 예문 - 해석"
            ],
            "background": {{
                "translation": "이 문장의 가장 자연스러운 우리말 해석 (의역 포함)",
                "pronunciation": "원어민의 연음을 반영한 자연스러운 한글 발음 표기",
                "words": "핵심 단어와 숙어 정리 (뜻 포함)",
                "context": "이 문장이 쓰이는 문화적 배경이나 뉘앙스 설명"
            }}
        }}
        문장: "{text}"
        """
        raw_text = self._call_ai(prompt)
        if "🚨" in raw_text: return {"grammar": "에러", "examples": ["에러"], "background": {}}
        
        clean_text = raw_text.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        try:
            return json.loads(match.group(0)) if match else {"grammar": "파싱 에러", "examples": [], "background": {}}
        except:
            return {"grammar": "JSON 디코딩 에러", "examples": [], "background": {}}

    def get_pattern_study(self, pattern_text):
        prompt = f"""
        패턴 '{pattern_text}'에 대한 설명과 예문 10개를 순수 JSON으로 작성하세요.
        {{"explanation": "패턴 설명", "examples": ["1. 영어 - 해석", "2. 영어 - 해석", "3. 영어 - 해석", "4. 영어 - 해석", "5. 영어 - 해석", "6. 영어 - 해석", "7. 영어 - 해석", "8. 영어 - 해석", "9. 영어 - 해석", "10. 영어 - 해석"]}}
        """
        raw_text = self._call_ai(prompt)
        if "🚨" in raw_text: return {"explanation": raw_text, "examples": []}
        
        clean_text = raw_text.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        return json.loads(match.group(0)) if match else {"explanation": "파싱 실패", "examples": []}

    def extract_text(self, uploaded_file):
        text = ""
        file_type = uploaded_file.name.split('.')[-1].lower()
        if file_type == 'pdf':
            pdf_reader = PdfReader(uploaded_file)
            for page in pdf_reader.pages: text += page.extract_text() + "\n"
        elif file_type == 'docx':
            doc = Document(io.BytesIO(uploaded_file.read()))
            for para in doc.paragraphs: text += para.text + "\n"
        return text

    def split_into_sentences(self, text, split_mode="마침표"):
        if "줄바꿈" in split_mode:
            lines = text.split('\n')
            return [line.strip() for line in lines if len(line.strip()) > 2]
        else:
            sentences = re.split(r'(?<=[.!?]) +', text.strip().replace('\n', ' '))
            return [s.strip() for s in sentences if len(s.strip()) > 5]

# ============================================================
# [3] 150 핵심 패턴 데이터
# ============================================================
@st.cache_data
def get_unique_150_patterns():
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
# [4] UI 메인 구성
# ============================================================
if 'study_log' not in st.session_state: st.session_state.study_log = []
if 'all_sentences' not in st.session_state: st.session_state.all_sentences = []
if 'current_text' not in st.session_state: st.session_state.current_text = ""
if 'current_page' not in st.session_state: st.session_state.current_page = 0
if 'page_translations' not in st.session_state: st.session_state.page_translations = {}

# 🗂️ 사이드바
with st.sidebar:
    st.header("⚙️ AI 엔진 선택")
    st.write("메인 엔진이 막히면 초고속 모델로 교체하세요!")
    selected_engine = st.radio(
        "사용할 무료 AI 모델:", 
        ["Llama 3.1 (메타/초고속 무료)", "Gemini 2.5 (구글/무료)"]
    )
    
    st.divider()
    st.header("📚 나만의 서재 (DB)")
    with st.spinner("구글 시트에서 서재를 불러오는 중..."):
        library = load_library()
        
    if library:
        saved_titles = sorted(list(library.keys()))
        selected_doc = st.selectbox("저장된 문서 목록", ["선택하세요"] + saved_titles)
        
        col_load, col_del = st.columns(2)
        with col_load:
            if st.button("📂 불러오기", use_container_width=True) and selected_doc != "선택하세요":
                st.session_state.current_text = library[selected_doc]['text']
                st.session_state.all_sentences = MultiAIEngine(selected_engine).split_into_sentences(st.session_state.current_text, "마침표")
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

tutor = MultiAIEngine(selected_engine)

st.title(f"🎓 AI 영어 마스터")
st.caption(f"🚀 현재 작동 중인 엔진: **{selected_engine}** | 🗄️ DB: **구글 시트 연동 됨**")

tabs = st.tabs(["🔍 스마트 문서 분석", "🧩 150 핵심 패턴", "📅 학습 일정 관리"])

with tabs[0]:
    st.subheader("새 문서 업로드 및 분석")
    mode = st.radio("입력 방식", ["파일 첨부", "텍스트 직접 입력"], horizontal=True)
    
    temp_text = ""
    if mode == "파일 첨부":
        file = st.file_uploader("파일을 올려주세요 (PDF, DOCX)", type=["pdf", "docx"])
        if file: temp_text = tutor.extract_text(file)
    else:
        temp_text = st.text_area("영어 문장이나 대본을 붙여넣으세요", height=100)

    st.write("---")
    split_mode = st.radio("✂️ 문장 나누기 기준", ["마침표 기준 (일반 문서, 소설 등)", "줄바꿈 기준 (대본, 자막 등)"], horizontal=True)

    if temp_text:
        col_apply, col_save, _ = st.columns([2, 2, 6])
        with col_apply:
            if st.button("🚀 이 문서 분석 시작", type="primary"):
                st.session_state.current_text = temp_text
                st.session_state.all_sentences = tutor.split_into_sentences(temp_text, split_mode)
                st.session_state.current_page = 0
                st.session_state.page_translations = {}
                st.rerun()
        with col_save:
            with st.popover("💾 구글 시트 DB에 저장"):
                doc_title = st.text_input("문서 제목을 입력하세요:")
                if st.button("저장 확정"):
                    if doc_title:
                        with st.spinner("클라우드에 안전하게 저장 중..."):
                            save_to_library(doc_title, temp_text)
                        st.success("저장 완료!")
                        st.rerun()
                    else:
                        st.error("제목을 입력하세요.")

    st.divider()

    if st.session_state.all_sentences:
        page_size = 10
        total_pages = math.ceil(len(st.session_state.all_sentences) / page_size)
        current_page = st.session_state.current_page
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, len(st.session_state.all_sentences))
        current_chunk = st.session_state.all_sentences[start_idx:end_idx]

        if current_page not in st.session_state.page_translations:
            with st.spinner(f"번역 중입니다..."):
                st.session_state.page_translations[current_page] = tutor.bulk_translate(current_chunk)
        
        translations = st.session_state.page_translations[current_page]
        
        df = pd.DataFrame({
            "No.": range(start_idx + 1, end_idx + 1),
            "English (원문)": current_chunk,
            "Korean (직관적 해석)": translations[:len(current_chunk)]
        })
        df.set_index("No.", inplace=True)
        
        st.write("### 📖 병렬 학습 리스트 (줄을 클릭하면 분석이 나옵니다)")
        
        df_config = {
            "English (원문)": st.column_config.TextColumn(width="large"),
            "Korean (직관적 해석)": st.column_config.TextColumn(width="large")
        }

        try:
            selection = st.dataframe(
                df, 
                hide_index=False,
                column_config=df_config,
                use_container_width=True,
                row_height=90,
                on_select="rerun", 
                selection_mode="single-row"
            )
        except TypeError:
            selection = st.dataframe(
                df, 
                hide_index=False,
                column_config=df_config,
                use_container_width=True,
                on_select="rerun", 
                selection_mode="single-row"
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

        selected_rows = selection.get("selection", {}).get("rows", [])
        if selected_rows:
            target_s = current_chunk[selected_rows[0]]
            st.divider()
            st.markdown(f"### 🕵️‍♂️ {start_idx + selected_rows[0] + 1}번 문장 심층 리포트")
            
            with st.spinner(f"초고속 상세 분석 중..."):
                analysis = tutor.deep_analyze(target_s)
                
                c1, c2, c3 = st.columns(3)
                
                c1.success(f"📐 **문법 & 형식 상세 강의**\n\n{analysis.get('grammar', '정보 없음')}")
                
                examples_text = "\n\n".join([f"- {ex}" for ex in analysis.get('examples', [])])
                c2.warning(f"💡 **응용 실전 예시**\n\n{examples_text}")
                
                bg = analysis.get('background', {})
                bg_text = f"🎯 **자연스러운 해석:**\n{bg.get('translation', '정보 없음')}\n\n" \
                          f"🗣️ **원어민 발음:**\n{bg.get('pronunciation', '정보 없음')}\n\n" \
                          f"📝 **단어/숙어:**\n{bg.get('words', '정보 없음')}\n\n" \
                          f"🌍 **배경/뉘앙스:**\n{bg.get('context', '정보 없음')}"
                c3.error(f"🔍 **문장 심층 지식**\n\n{bg_text}")

with tabs[1]:
    st.subheader("🚀 150 핵심 패턴 정복")
    all_patterns = get_unique_150_patterns()
    
    with st.container(height=350):
        selected_p = st.radio("패턴 리스트", all_patterns, label_visibility="collapsed")
    
    if st.button("이 패턴 집중 공략하기 🚀"):
        with st.spinner(f"맞춤 예문을 생성 중입니다..."):
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
                st.success("저장되었습니다!")

with tabs[2]:
    st.subheader("📅 나의 학습 히스토리")
    if st.session_state.study_log:
        st.table(pd.DataFrame(st.session_state.study_log).sort_values("날짜", ascending=False))
    else:
        st.write("아직 학습 기록이 없습니다.")
