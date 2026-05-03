import streamlit as st
from google import genai
import json
import re
import os
from PyPDF2 import PdfReader
from docx import Document
import io
import pandas as pd
from datetime import datetime, timedelta
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
st.set_page_config(page_title="AI 영어 마스터", page_icon="🎓", layout="wide")

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
/* 추가된 뉴스 카드 CSS */
.news-card {
    background-color: #ffffff;
    border-left: 4px solid #ff4b4b;
    padding: 15px;
    border-radius: 5px;
    margin-bottom: 15px;
    box-shadow: 1px 1px 4px rgba(0,0,0,0.1);
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
# [1] 데이터 관리 엔진 (DB 연동 완벽 캐싱)
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
        error_details = traceback.format_exc()
        st.error("🚨 **[DB 연결 실패]** 🚨")
        st.code(error_details, language="bash")
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
            d_key = real_keys.get('date')
            
            title_val = row.get(t_key) if t_key else None
            text_val = row.get(txt_key, '') if txt_key else ''
            date_val = row.get(d_key, '') if d_key else ''
            
            if title_val:
                library[str(title_val)] = {"text": str(text_val), "date": str(date_val)}
        return library
    except Exception as e:
        return {}

def save_to_library(title, text):
    sheet = get_gsheet()
    if not sheet: return
    try:
        records = sheet.get_all_records()
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        row_idx = None
        for i, row in enumerate(records):
            real_keys = {k.lower(): k for k in row.keys()}
            t_key = real_keys.get('title')
            if t_key and str(row.get(t_key)) == str(title):
                row_idx = i + 2 
                break
        if row_idx:
            sheet.update_cell(row_idx, 2, text)
            sheet.update_cell(row_idx, 3, date_str)
        else:
            sheet.append_row([title, text, date_str])
        load_library.clear()
    except:
        sheet.append_row([title, text, datetime.now().strftime("%Y-%m-%d %H:%M")])
        load_library.clear()

def delete_from_library(title):
    sheet = get_gsheet()
    if not sheet: return
    try:
        records = sheet.get_all_records()
        for i, row in enumerate(records):
            real_keys = {k.lower(): k for k in row.keys()}
            t_key = real_keys.get('title')
            if t_key and str(row.get(t_key)) == str(title):
                sheet.delete_rows(i + 2)
                load_library.clear()
                break
    except:
        pass

# ============================================================
# [2] 하이브리드 멀티 AI 엔진 (에러 원천 봉쇄형)
# ============================================================
def extract_safe_json(text):
    """무적의 JSON 추출기: AI의 잡담과 오류를 뚫고 알맹이만 가져옴"""
    try:
        match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
        if match:
            return json.loads(match.group(0))
    except:
        pass
    return None

class MultiAIEngine:
    def __init__(self, selected_engine):
        self.engine_type = selected_engine

    def _call_ai(self, prompt, expect_json=True):
        try:
            if self.engine_type == "Gemini 2.5 (구글/무료)":
                if not GEMINI_API_KEY: return "🚨 Gemini API 키가 없습니다."
                client = genai.Client(api_key=GEMINI_API_KEY)
                response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                return response.text

            elif self.engine_type == "Llama 3.1 (메타/초고속 무료)":
                if not GROQ_API_KEY: return "🚨 Groq API 키가 없습니다."
                client = Groq(api_key=GROQ_API_KEY)
                kwargs = {
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2, 
                    "max_tokens": 4000
                }
                if expect_json:
                    kwargs["response_format"] = {"type": "json_object"}

                response = client.chat.completions.create(**kwargs)
                return response.choices[0].message.content
        except Exception as e:
            return f"🚨 {self.engine_type} 서버 에러: {str(e)}"

    # [신규 추가] 1. 오늘의 속담 (중복 방지)
    def get_daily_proverb(self, exclude_list):
        prompt = f"""
        당신은 지혜로운 학자입니다. 동서양의 실존하는 유명 속담 중 하나를 선정하세요.
        단, 다음 리스트에 있는 속담은 피해주세요: {exclude_list}
        반드시 JSON 형식으로만 응답하세요.
        {{
            "proverb": "속담 원문",
            "meaning": "속담의 깊은 뜻 풀이",
            "origin": "속담의 유래나 배경"
        }}
        """
        return extract_safe_json(self._call_ai(prompt, expect_json=True))

    # [신규 추가] 2. 사자성어 (한자 훈음 정확도 강화, 거짓 방지)
    def get_idiom_story(self, exclude_list):
        prompt = f"""
        당신은 역사와 고전에 정통한 학자입니다. 실존하는 정확한 사자성어를 하나 선정하세요.
        단, 다음 리스트는 피해주세요: {exclude_list}
        각 한자의 뜻과 소리(훈음)를 엉터리로 짓지 말고 정확히 풀이하세요.
        반드시 JSON 형식으로만 응답하세요.
        {{
            "idiom": "한자(四字成語)",
            "pronunciation": "독음(한글)",
            "hanja_info": "각 한자별 뜻과 음 (예: 學 배울 학, 而 말 이...)",
            "meaning": "사자성어의 전체 속뜻",
            "story": "역사적 유래나 고사 이야기",
            "lesson": "오늘날의 교훈"
        }}
        """
        return extract_safe_json(self._call_ai(prompt, expect_json=True))

    # [신규 추가] 3. 어제자 뉴스 (상상 금지, 실제 채널 기반)
    def get_realtime_news(self):
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y년 %m월 %d일")
        prompt = f"""
        당신은 팩트 체커이자 뉴스 큐레이터입니다. {yesterday} 기준으로 대한민국이나 전 세계에서 실제로 보도된 주요 뉴스 TOP 10을 정리하세요.
        절대 상상하거나 지어내지 마세요. KBS, MBC, SBS, YTN 등 실제 언론사에서 보도된 내용만 다루세요.
        반드시 JSON 형식으로만 응답하세요.
        {{
            "date": "{yesterday}",
            "news": [
                {{"title": "뉴스 제목", "channel": "보도 매체 이름", "summary": "기사 1줄 요약"}}
            ]
        }}
        """
        return extract_safe_json(self._call_ai(prompt, expect_json=True))

    # (이하 기존 영어 분석 함수들 그대로 유지)
    def bulk_translate(self, sentences):
        if not sentences: return []
        
        # 🚨 [패치 3 & 4] 줄 어긋남 방지 JSON Array 강제 매커니즘 & 영어 역류 금지
        prompt = f"""
        당신은 넷플릭스 전문 번역가입니다. 제공된 텍스트를 문맥에 맞게 가장 자연스러운 한국어 구어체로 번역하세요.
        
        [CRITICAL RULE]
        입력된 문장은 정확히 {len(sentences)}개입니다. 
        반드시 "translations"라는 키를 가진 JSON 객체로 응답하고, 그 안에 {len(sentences)}개의 '한국어 번역문' 문자열(String)만 순서대로 배열(Array)에 담으세요.
        절대 영어를 그대로 복사하거나 합치지 마세요.
        
        출력 형식:
        {{
            "translations": [
                "첫 번째 번역",
                "두 번째 번역",
                ...
            ]
        }}
        
        입력 데이터:
        {json.dumps(sentences)}
        """
        raw_text = self._call_ai(prompt, expect_json=True)
        if "🚨" in raw_text: return ["서버 에러 (AI 응답 불가)"] * len(sentences)
        
        data = extract_safe_json(raw_text)
        final_res = []
        
        if data and isinstance(data, dict) and "translations" in data:
            trans_list = data["translations"]
            for i in range(len(sentences)):
                if i < len(trans_list):
                    val = str(trans_list[i]).replace("\n", " ").strip()
                    # 🚨 영어 섞임(역류) 필터링
                    eng_chars = len(re.findall(r'[a-zA-Z]', val))
                    kor_chars = len(re.findall(r'[가-힣]', val))
                    if eng_chars > kor_chars * 2 and kor_chars < 3:
                        final_res.append("번역 실패 (AI 영어 출력 오류)")
                    else:
                        final_res.append(val)
                else:
                    final_res.append("번역 누락 (AI 응답 잘림)")
            return final_res
            
        return ["파싱 실패 (형식 오류)"] * len(sentences)

    def deep_analyze(self, text):
        # 🚨 [패치 5] JSON 디코딩 에러 방지 - AI에게 HTML 작성 금지!
        prompt = f"""
        당신은 미드 전문 영어 강사입니다. 아래 대사를 분석하여 순수 "JSON object" 형식으로만 응답하세요.
        {{
            "cefr": "이 문장의 난이도 (A1 ~ C2)",
            "grammar": "문장의 구조(형식)와 핵심 문법 알기 쉽게 설명",
            "examples": ["1. 비슷한 회화 예문 - 해석", "2. 비슷한 회화 예문 - 해석"],
            "translations": {{
                "literal": "한국어 어순에 맞춘 직독직해",
                "natural": "자연스러운 구어체 의역"
            }},
            "words": [
                {{"word": "영단어", "meaning": "한글 뜻", "pronunciation": "원어민 연음 한국어 표기 (예: 워러, 체끼라웃)"}}
            ],
            "context": "이 대사가 쓰이는 극중 상황 설명",
            "quiz": {{"question": "빈칸 ___ 뚫기 퀴즈", "hint": "힌트(뜻)", "answer": "정답 영단어"}}
        }}
        문장: "{text}"
        """
        raw_text = self._call_ai(prompt, expect_json=True)
        if "🚨" in raw_text: return None
        return extract_safe_json(raw_text)

    def get_pattern_study(self, pattern_text):
        prompt = f"""
        회화 패턴 '{pattern_text}'에 대한 설명과 실생활 구어체 예문 10개를 "JSON object" 형식으로 작성하세요.
        {{"explanation": "패턴 설명", "examples": ["1. 영어 - 해석", "2. 영어 - 해석"]}}
        """
        raw_text = self._call_ai(prompt, expect_json=True)
        if "🚨" in raw_text: return None
        return extract_safe_json(raw_text)

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

    def split_into_sentences(self, text):
        # 🚨 [패치 1 & 2] 입력 모드 통일 & 오토 대본 스캐너 적용
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        clean_lines = []
        
        # 자막 타임코드 및 찌꺼기 제거
        for l in lines:
            if re.match(r'^\d+$', l) or '-->' in l: continue
            clean_lines.append(l)
            
        # 대본(화자) 여부 자동 판독 (상위 15줄 스캔)
        speaker_pattern = re.compile(r'^([a-zA-Z가-힣0-9\s\.\-\[\]]{1,20}):')
        script_cues = sum(1 for l in clean_lines[:15] if speaker_pattern.match(l))
        is_script = script_cues >= 1
        
        sentences = []
        if is_script:
            current = ""
            for line in clean_lines:
                if speaker_pattern.match(line):
                    if current: sentences.append(current.strip())
                    current = line
                else:
                    if current: current += " " + line
                    else: current = line
            if current: sentences.append(current.strip())
            return [s for s in sentences if len(s.split()) >= 2]
        else:
            joined = " ".join(clean_lines)
            raw_sents = re.split(r'(?<=[.!?])\s+', joined)
            return [s.strip() for s in raw_sents if len(s.strip()) > 3]

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

# [신규 추가] 세션 상태 초기화 (중복 방지용)
if 'used_proverbs' not in st.session_state: st.session_state.used_proverbs = []
if 'used_idioms' not in st.session_state: st.session_state.used_idioms = []

with st.sidebar:
    st.header("⚙️ AI 엔진 선택")
    st.write("메인 엔진이 막히면 초고속 모델로 교체하세요!")
    selected_engine = st.radio("사용할 무료 AI 모델:", ["Llama 3.1 (메타/초고속 무료)", "Gemini 2.5 (구글/무료)"])
    st.divider()
    col_db1, col_db2 = st.columns([3, 1])
    with col_db1: st.header("📚 나만의 서재")
    with col_db2: 
        if st.button("🔄", help="서재 새로고침"): 
            load_library.clear()
            st.rerun()

    library = load_library()
        
    if library:
        saved_titles = sorted(list(library.keys()))
        selected_doc = st.selectbox("저장된 문서 목록", ["선택하세요"] + saved_titles)
        
        col_load, col_del = st.columns(2)
        with col_load:
            if st.button("📂 불러오기", use_container_width=True) and selected_doc != "선택하세요":
                st.session_state.current_text = library[selected_doc]['text']
                # 🚨 오토 스캐너 적용
                st.session_state.all_sentences = MultiAIEngine(selected_engine).split_into_sentences(st.session_state.current_text)
                st.session_state.current_page = 0
                st.session_state.page_translations = {}
                st.rerun()
        with col_del:
            if st.button("🗑️ 삭제", use_container_width=True) and selected_doc != "선택하세요":
                delete_from_library(selected_doc)
                st.toast(f"'{selected_doc}' 문서가 삭제되었습니다!", icon="🗑️")
                time.sleep(1)
                st.rerun()
    else:
        st.info("저장된 문서가 없습니다.")

tutor = MultiAIEngine(selected_engine)

st.title(f"🎓 AI 영어 마스터")
st.caption(f"🚀 작동 중인 엔진: **{selected_engine}** | 🗄️ DB: **캐시 최적화 연동 완료**")

# [탭 구성 수정] 속담/사자성어, 뉴스 탭을 추가했습니다. 기존 탭은 그대로 유지됩니다.
tabs = st.tabs(["🔍 스마트 대본 분석", "🧩 150 핵심 패턴", "📜 오늘의 지혜", "📰 어제자 뉴스", "📅 학습 일정 관리"])

# --- 기존 소스: 탭 0 ---
with tabs[0]:
    with st.expander("📝 문서 업로드 및 새 텍스트 입력 (클릭해서 열기/접기)", expanded=not bool(st.session_state.current_text)):
        mode = st.radio("입력 방식", ["파일 첨부", "텍스트 직접 입력"], horizontal=True)
        temp_text = ""
        if mode == "파일 첨부":
            file = st.file_uploader("파일을 올려주세요 (PDF, DOCX)", type=["pdf", "docx"])
            if file: temp_text = tutor.extract_text(file)
        else:
            temp_text = st.text_area("영어 문장, 대본, 자막을 붙여넣으세요 (AI가 형식을 자동 감지합니다)", height=150)

        col_apply, col_save, _ = st.columns([2, 2, 6])
        with col_apply:
            if st.button("🚀 이 문서 분석 시작", type="primary"):
                if temp_text.strip(): 
                    st.session_state.current_text = temp_text
                    st.session_state.all_sentences = tutor.split_into_sentences(temp_text)
                    st.session_state.current_page = 0
                    st.session_state.page_translations = {}
                    st.rerun()
                else:
                    st.toast("텍스트를 먼저 입력해주세요!", icon="⚠️")
        with col_save:
            with st.popover("💾 구글 시트 DB에 저장"):
                doc_title = st.text_input("문서 제목을 입력하세요:")
                if st.button("저장 확정"):
                    if doc_title and temp_text.strip():
                        save_to_library(doc_title, temp_text)
                        st.toast(f"🎉 '{doc_title}' 문서 저장 완료!", icon="✅")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("제목과 내용을 확인하세요.")

    st.divider()

    if st.session_state.all_sentences:
        page_size = 20
        total_pages = max(1, math.ceil(len(st.session_state.all_sentences) / page_size))
        current_page = st.session_state.current_page
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, len(st.session_state.all_sentences))
        current_chunk = st.session_state.all_sentences[start_idx:end_idx]

        chunk_hash = hash(tuple(current_chunk))
        
        if st.session_state.page_translations.get("hash") != chunk_hash:
            with st.spinner(f"⚡ AI 번역 모드 가동 중..."):
                raw_trans = tutor.bulk_translate(current_chunk)
                st.session_state.page_translations = {"hash": chunk_hash, "data": raw_trans}
        
        translations = st.session_state.page_translations["data"]
        clean_chunk = [str(s).replace("\n", " ").strip() for s in current_chunk]
        
        # 🚨 [패치 8] 직독직해 제거, 1:1 완벽 보장 표 생성
        df = pd.DataFrame({
            "No.": range(start_idx + 1, end_idx + 1),
            "English (원문)": clean_chunk,
            "Korean (자연스러운 해석)": translations[:len(clean_chunk)]
        })
        df.set_index("No.", inplace=True)
        
        col_list, col_btn = st.columns([8, 2])
        with col_list:
            st.write("### 📖 병렬 학습 리스트 (문장을 클릭하세요!)")
        with col_btn:
            if st.button("📝 학습 달력에 출석 기록", use_container_width=True):
                st.session_state.study_log.append({"날짜": datetime.now().strftime("%Y-%m-%d %H:%M"), "유형": "문서 분석 완료", "내용": f"{start_idx+1}~{end_idx}번 문장"})
                st.toast("출석 도장이 찍혔습니다!", icon="📅")
        
        # 🚨 [패치 7] 자동 줄간격 폐기, 수동 슬라이더 단독 배치 (기본값 40px로 여유롭게)
        row_h = st.slider("↕️ 리스트 줄 간격 수동 조절", min_value=30, max_value=200, value=40, step=5)
        
        df_config = {
            "English (원문)": st.column_config.TextColumn(width="large"),
            "Korean (자연스러운 해석)": st.column_config.TextColumn(width="large")
        }

        try:
            selection = st.dataframe(df, hide_index=False, column_config=df_config, use_container_width=True, row_height=row_h, on_select="rerun", selection_mode="single-row")
        except:
            selection = st.dataframe(df, hide_index=False, column_config=df_config, use_container_width=True, on_select="rerun", selection_mode="single-row")

        col_prev, col_info, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("◀ 이전 페이지") and current_page > 0:
                st.session_state.current_page -= 1
                st.rerun()
        with col_info:
            st.markdown(f"<div style='text-align:center;'><b>{current_page+1} / {total_pages} 페이지</b></div>", unsafe_allow_html=True)
        with col_next:
            if st.button("다음 페이지 ▶") and current_page < total_pages - 1:
                st.session_state.current_page += 1
                st.rerun()

        selected_rows = selection.get("selection", {}).get("rows", [])
        if selected_rows:
            target_s = clean_chunk[selected_rows[0]]
            st.divider()
            st.markdown(f"### 🕵️‍♂️ {start_idx + selected_rows[0] + 1}번 문장 심층 멘토링")
            
            with st.spinner(f"초고속 심층 분석 및 스마트 단어장 생성 중..."):
                analysis = tutor.deep_analyze(target_s)
                
                if analysis:
                    # 🚨 파이썬 자체 호버 HTML 생성기 (JSON 에러 원천 차단)
                    words_list = analysis.get("words", [])
                    if words_list and isinstance(words_list, list):
                        html_parts = []
                        words_in_sentence = target_s.split()
                        for word in words_in_sentence:
                            clean_word = re.sub(r'[^\w\']', '', word).lower()
                            matched = False
                            for w_info in words_list:
                                if w_info.get("word", "").lower() == clean_word:
                                    w_mean = str(w_info.get("meaning", "")).replace("'", "&#39;").replace('"', '&quot;')
                                    w_pron = str(w_info.get("pronunciation", "")).replace("'", "&#39;").replace('"', '&quot;')
                                    html_parts.append(f"<span class='hover-word' title='뜻: {w_mean} | 발음: {w_pron}'>{word}</span>")
                                    matched = True
                                    break
                            if not matched:
                                html_parts.append(word)
                        hover_html = " ".join(html_parts)
                    else:
                        hover_html = target_s

                    cefr_level = analysis.get("cefr", "판독 불가")
                    st.markdown(f"<div class='cefr-badge'>📊 실전 난이도: {cefr_level}</div>", unsafe_allow_html=True)

                    grammar_str = str(analysis.get('grammar', '정보 없음'))
                    
                    ex_list = analysis.get('examples', [])
                    examples_text = "\n\n".join([f"- {str(x)}" for x in ex_list])

                    bg = analysis.get('background', {})
                    trans = analysis.get('translations', {})
                    lit_trans = str(trans.get('literal', '정보 없음'))
                    nat_trans = str(trans.get('natural', '정보 없음'))
                    pronun_str = str(bg.get('pronunciation', '정보 없음'))
                    context_str = str(bg.get('context', '정보 없음'))
                    
                    words_str = "\n".join([f"- **{w.get('word','')}**: {w.get('meaning','')} [{w.get('pronunciation','')}]" for w in words_list]) if words_list else "정보 없음"

                    st.info("🖱️ **스마트 단어장:** 아래 문장의 단어 위에 마우스를 슥~ 올려보세요! 숨겨진 뜻과 원어민 찰진 연음이 툴팁으로 뜹니다.")
                    st.markdown(f"<div class='info-box' style='font-size: 1.5em; line-height: 2.0; font-weight: bold;'>{hover_html}</div>", unsafe_allow_html=True)
                    
                    c1, c2, c3 = st.columns(3)
                    c1.success(f"📐 **문법 & 형식 핵심 강의**\n\n{grammar_str}")
                    c2.warning(f"💡 **응용 실전 예시**\n\n{examples_text}")
                    bg_text = f"🎯 **한국어 어순 직독직해:**\n{lit_trans}\n\n" \
                              f"🎯 **자연스러운 의역:**\n{nat_trans}\n\n" \
                              f"🗣️ **원어민 실제 발음:**\n{pronun_str}\n\n" \
                              f"📝 **단어장:**\n{words_str}\n\n" \
                              f"🌍 **극중 뉘앙스/배경:**\n{context_str}"
                    c3.error(f"🔍 **문장 심층 지식**\n\n{bg_text}")

                    st.divider()
                    with st.expander("🏆 실력 점검! AI 빈칸 채우기 퀴즈 (클릭해서 열기)"):
                        quiz_data = analysis.get("quiz", {})
                        st.write(f"**Q. 다음 문장의 빈칸에 들어갈 알맞은 단어는?**")
                        st.markdown(f"### {quiz_data.get('question', '퀴즈 데이터를 불러오지 못했습니다.')}")
                        st.caption(f"💡 힌트: {quiz_data.get('hint', '')}")
                        
                        if st.button("정답 확인하기 🔍", key=f"quiz_btn_{start_idx + selected_rows[0]}"):
                            st.success(f"🎉 정답: **{quiz_data.get('answer', '')}**")
                else:
                    st.error("🚨 AI 파싱 에러: 다시 한 번 클릭해주세요.")

# --- 기존 소스: 탭 1 ---
with tabs[1]:
    st.subheader("🚀 150 핵심 패턴 정복")
    all_patterns = get_unique_150_patterns()
    with st.container(height=350): selected_p = st.radio("패턴 리스트", all_patterns, label_visibility="collapsed")
    if st.button("이 패턴 집중 공략하기 🚀"):
        with st.spinner(f"맞춤 예문을 생성 중입니다..."):
            clean_pattern = selected_p.split(" : ")[-1] if " : " in selected_p else selected_p
            p_data = tutor.get_pattern_study(clean_pattern)
            if p_data:
                st.session_state.p_study = p_data
                st.session_state.p_title = selected_p
            else:
                st.toast("AI 에러! 다시 눌러주세요.", icon="🚨")

    if 'p_study' in st.session_state:
        st.markdown(f"### 💡 {st.session_state.p_title}")
        st.info(st.session_state.p_study.get("explanation", "설명 데이터를 불러오지 못했습니다."))
        st.write("#### ✍️ 실전 회화 예문 10선")
        for ex in st.session_state.p_study.get("examples", []): st.write(f"- {ex}")
        st.divider()
        if st.checkbox("✅ 오늘 이 패턴 마스터!"):
            st.balloons()
            if st.button("학습 달력에 도장 찍기"):
                st.session_state.study_log.append({"날짜": datetime.now().strftime("%Y-%m-%d %H:%M"), "유형": "패턴 집중 학습", "내용": st.session_state.p_title})
                st.toast("저장되었습니다!", icon="✅")

# --- [신규 추가] 탭 2: 오늘의 지혜 (속담 & 사자성어) ---
with tabs[2]:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🍎 오늘의 속담")
        st.caption("클릭할 때마다 새로운 동서양 속담이 나옵니다. (100개까지 중복 방지)")
        if st.button("새 속담 가져오기 🔄"):
            with st.spinner("지혜의 문장을 찾는 중..."):
                res = tutor.get_daily_proverb(st.session_state.used_proverbs)
                if res:
                    st.session_state.proverb_data = res
                    st.session_state.used_proverbs.append(res['proverb'])
                    # 100개가 넘으면 오래된 것부터 삭제 (무한 루프 방지)
                    if len(st.session_state.used_proverbs) > 100: st.session_state.used_proverbs.pop(0)

        if 'proverb_data' in st.session_state:
            p = st.session_state.proverb_data
            st.info(f"### {p.get('proverb', '')}")
            st.write(f"**풀이:** {p.get('meaning', '')}")
            with st.expander("📖 속담의 유래"):
                st.write(p.get('origin', ''))

    with col2:
        st.subheader("📚 오늘의 사자성어")
        st.caption("정확한 한자 풀이와 고전을 배웁니다. (100개까지 중복 방지)")
        if st.button("새 사자성어 가져오기 🔄"):
            with st.spinner("고서(古書)를 탐독하는 중..."):
                res = tutor.get_idiom_story(st.session_state.used_idioms)
                if res:
                    st.session_state.idiom_data = res
                    st.session_state.used_idioms.append(res['idiom'])
                    if len(st.session_state.used_idioms) > 100: st.session_state.used_idioms.pop(0)

        if 'idiom_data' in st.session_state:
            i = st.session_state.idiom_data
            st.success(f"### {i.get('idiom', '')} ({i.get('pronunciation', '')})")
            st.markdown(f"**한자 풀이:** `{i.get('hanja_info', '')}`")
            st.write(f"**의미:** {i.get('meaning', '')}")
            with st.expander("📜 역사적 유래 및 교훈"):
                st.write(i.get('story', ''))
                st.divider()
                st.write(f"💡 **오늘의 교훈:** {i.get('lesson', '')}")

# --- [신규 추가] 탭 3: 어제자 뉴스 ---
with tabs[3]:
    st.subheader("📰 어제자 주요 뉴스 TOP 10")
    st.caption("AI가 상상하지 않고, 실제 언론 매체에 보도된 내용만 팩트 체크하여 요약합니다.")
    
    if st.button("뉴스 업데이트 🔄"):
        with st.spinner("어제자 보도 채널을 분석 중입니다..."):
            res = tutor.get_realtime_news()
            if res:
                st.session_state.news_date = res.get('date', '')
                st.session_state.news_list = res.get('news', [])
            else:
                st.error("뉴스를 가져오는 데 실패했습니다.")

    if 'news_list' in st.session_state:
        st.write(f"📅 **기준일:** {st.session_state.news_date}")
        for idx, item in enumerate(st.session_state.news_list):
            st.markdown(f"""
            <div class="news-card">
                <span style="color:gray; font-size:0.8em; font-weight:bold;">[{item.get('channel', '종합 언론')}]</span><br>
                <strong style="font-size:1.1em;">{idx+1}. {item.get('title', '')}</strong>
                <p style="margin-top:5px; color:#444;">{item.get('summary', '')}</p>
            </div>
            """, unsafe_allow_html=True)

# --- 기존 소스: 탭 2 -> 탭 4로 이동 ---
with tabs[4]:
    st.subheader("📅 나의 학습 히스토리")
    if st.session_state.study_log: 
        st.table(pd.DataFrame(st.session_state.study_log).sort_values("날짜", ascending=False))
    else: 
        st.write("아직 학습 기록이 없습니다. 오늘부터 첫 발걸음을 떼어보세요!")
