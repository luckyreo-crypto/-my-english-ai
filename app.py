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
# 🚨 화면 설정
# ============================================================
st.set_page_config(page_title="AI 영어 마스터", page_icon="🎓", layout="wide")

# ============================================================
# 🔐 보안 및 설정
# ============================================================
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    APP_PASSWORD = st.secrets["APP_PASSWORD"]
except:
    st.error("🚨 보안 설정(Secrets)이 완료되지 않았습니다. 관리자에게 문의하세요.")
    st.stop()

DB_FILE = "my_english_docs.json"

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
# [1] 데이터 관리 엔진
# ============================================================
def load_library():
    if not os.path.exists(DB_FILE):
        return {}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            if not content: return {}
            return json.loads(content)
    except:
        return {}

def save_to_library(title, text):
    data = load_library()
    data[title] = {
        "text": text,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def delete_from_library(title):
    data = load_library()
    if title in data:
        del data[title]
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

# ============================================================
# [2] AI 백엔드 엔진 (🔥 세상에서 가장 가벼운 gemini-1.5-flash-8b 적용!)
# ============================================================
class EnglishTutorEngine:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)

    def bulk_translate(self, sentences):
        if not sentences: return []
        dict_sentences = {str(i): s for i, s in enumerate(sentences)}
        prompt = f"""
        당신은 1:1 직독직해 전문 번역기입니다. 아래 JSON의 번호를 유지하며 영어 문장을 한국어로 번역하세요.
        입력 데이터: {json.dumps(dict_sentences)}
        """
        try:
            # 🚀 초경량 모델 적용
            response = self.client.models.generate_content(model='gemini-1.5-flash-8b', contents=prompt)
            clean_text = response.text.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_text, re.DOTALL)
            if match: 
                result_dict = json.loads(match.group(0))
                return [result_dict.get(str(i), "번역 누락") for i in range(len(sentences))]
            return ["파싱 실패 (AI 응답 오류)"] * len(sentences)
        except Exception as e: 
            return [f"🚨 서버 통신 에러: {str(e)}"] * len(sentences)

    def deep_analyze(self, text):
        prompt = f"""
        당신은 초고속 영어 강사입니다. 아래 문장을 분석하여 순수 JSON으로 응답하세요. 단일 텍스트 문자열(String)로만 작성하세요.
        {{
            "grammar": "문법 강의 및 형식",
            "examples": "비슷한 예시 2~3개와 해석",
            "background": "주요 단어 뜻, 자연스러운 한글 발음"
        }}
        문장: "{text}"
        """
        try:
            # 🚀 초경량 모델 적용
            response = self.client.models.generate_content(model='gemini-1.5-flash-8b', contents=prompt)
            clean_text = response.text.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_text, re.DOTALL)
            return json.loads(match.group(0)) if match else {}
        except Exception as e: 
            return {"grammar": "에러", "examples": "에러", "background": f"🚨 상세 에러: {str(e)}"}

    def get_pattern_study(self, pattern_text):
        prompt = f"""
        당신은 영어 전문가입니다. 패턴 '{pattern_text}'에 대한 설명과 실전 예문 10개를 순수 JSON으로 작성하세요.
        {{
            "explanation": "이 패턴의 뉘앙스 설명",
            "examples": ["1. 영어 - 한국어", "2. 영어 - 한국어", "3. 영어 - 한국어", "4. 영어 - 한국어", "5. 영어 - 한국어", "6. 영어 - 한국어", "7. 영어 - 한국어", "8. 영어 - 한국어", "9. 영어 - 한국어", "10. 영어 - 한국어"]
        }}
        """
        try:
            # 🚀 초경량 모델 적용
            response = self.client.models.generate_content(model='gemini-1.5-flash-8b', contents=prompt)
            clean_text = response.text.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_text, re.DOTALL)
            if match: return json.loads(match.group(0))
            return {"explanation": "형식 이탈", "examples": []}
        except Exception as e: 
            return {"explanation": f"🚨 통신 에러: {str(e)}", "examples": []}

    def extract_text(self, uploaded_file):
        text = ""
        file_type = uploaded_file.name.split('.')[-1].lower()
        if file_type == 'pdf':
            pdf_reader = PdfReader(uploaded_file)
            for page in pdf_reader.pages: text += page.extract_text() + " "
        elif file_type == 'docx':
            doc = Document(io.BytesIO(uploaded_file.read()))
            for para in doc.paragraphs: text += para.text + " "
        return text

    def split_into_sentences(self, text):
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
# [4] 세션 초기화 및 UI 메인
# ============================================================
if 'study_log' not in st.session_state: st.session_state.study_log = []
if 'all_sentences' not in st.session_state: st.session_state.all_sentences = []
if 'current_text' not in st.session_state: st.session_state.current_text = ""
if 'current_page' not in st.session_state: st.session_state.current_page = 0
if 'page_translations' not in st.session_state: st.session_state.page_translations = {}

tutor = EnglishTutorEngine()

# 🗂️ 사이드바: 나만의 서재
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

with tabs[0]:
    st.subheader("새 문서 업로드 및 분석")
    mode = st.radio("입력 방식", ["파일 첨부", "텍스트 직접 입력"], horizontal=True)
    
    temp_text = ""
    if mode == "파일 첨부":
        file = st.file_uploader("파일을 올려주세요 (PDF, DOCX)", type=["pdf", "docx"])
        if file: temp_text = tutor.extract_text(file)
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
            if isinstance(data, dict): return "\n\n".join([f"- **{k}**: {v}" for k, v in data.items()])
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

with tabs[2]:
    st.subheader("📅 나의 학습 히스토리")
    if st.session_state.study_log:
        st.table(pd.DataFrame(st.session_state.study_log).sort_values("날짜", ascending=False))
    else:
        st.write("아직 학습 기록이 없습니다.")
