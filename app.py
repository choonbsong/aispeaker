import ast
import math
import operator
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st


st.set_page_config(page_title="한결 · AI 비서", page_icon="💬", layout="centered")

DEFAULT_MODEL = "openai/gpt-oss-120b"
GROQ_API_KEY = "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"  # Paste your key here for local use only; never commit or deploy it.
MAX_PROMPT_CHARS = 4000
MAX_HISTORY_MESSAGES = 20
SPEECH_KEY = "browser_speech_bridge"

SPEECH_HTML = """
<section aria-label="브라우저 음성 도구">
  <div class="speech-controls">
    <button id="speech-start" type="button">🎙️ 음성 입력 시작</button>
    <button id="speech-stop" type="button">⏹️ 녹음 종료</button>
    <button id="speech-cancel" type="button">🔇 음성 재생 중지</button>
    <span id="speech-status" role="status">브라우저 음성 기능을 확인하는 중입니다.</span>
  </div>
  <div id="speech-answers" aria-label="답변 음성 재생"></div>
</section>
"""

SPEECH_JS = """
export default function (component) {
  const { data, parentElement, setStateValue } = component
  const startButton = parentElement.querySelector("#speech-start")
  const stopButton = parentElement.querySelector("#speech-stop")
  const cancelButton = parentElement.querySelector("#speech-cancel")
  const statusElement = parentElement.querySelector("#speech-status")
  const answersElement = parentElement.querySelector("#speech-answers")
  if (!startButton || !stopButton || !cancelButton || !statusElement || !answersElement) return

  const state = parentElement.__hanGyeolSpeech || {
    recognition: null,
    transcriptId: 0,
    lastVoices: "",
    finalTranscript: "",
  }
  parentElement.__hanGyeolSpeech = state

  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition
  if (!Recognition) {
    statusElement.textContent = "이 브라우저는 음성 인식을 지원하지 않습니다. 아래 텍스트 입력을 이용해 주세요."
  } else {
    statusElement.textContent = "한국어 음성 입력을 사용할 수 있습니다. 마이크 권한이 필요합니다."
  }

  startButton.onclick = () => {
    if (!Recognition) return
    try {
      if (!state.recognition) {
        const recognition = new Recognition()
        recognition.lang = "ko-KR"
        recognition.continuous = true
        recognition.interimResults = true
        recognition.onstart = () => {
          state.finalTranscript = ""
          statusElement.textContent = "듣고 있습니다. 녹음을 끝내려면 종료 버튼을 누르세요."
          setStateValue("status", "listening")
        }
        recognition.onresult = (event) => {
          for (let i = event.resultIndex; i < event.results.length; i += 1) {
            if (event.results[i].isFinal) {
              state.finalTranscript += event.results[i][0].transcript + " "
            }
          }
          const text = state.finalTranscript.trim()
          if (!text) return
          state.transcriptId += 1
          setStateValue("transcript", { text, id: state.transcriptId })
        }
        recognition.onerror = (event) => {
          const messages = {
            "not-allowed": "마이크 권한이 거부되었습니다. 브라우저 사이트 설정에서 권한을 허용해 주세요.",
            "service-not-allowed": "브라우저 음성 인식 서비스가 허용되지 않았습니다.",
            "no-speech": "음성이 감지되지 않았습니다. 다시 시도하거나 텍스트를 입력해 주세요.",
            "audio-capture": "마이크를 찾을 수 없습니다. 연결 상태와 권한을 확인해 주세요."
          }
          const message = messages[event.error] || "음성 인식 중 문제가 발생했습니다. 텍스트 입력을 이용하거나 다시 시도해 주세요."
          statusElement.textContent = message
          setStateValue("status", message)
        }
        recognition.onend = () => {
          statusElement.textContent = "음성 입력이 끝났습니다. 인식 결과를 확인하고 수정한 뒤 전송하세요."
          setStateValue("status", "complete")
        }
        state.recognition = recognition
      }
      state.recognition.start()
    } catch (error) {
      statusElement.textContent = "음성 인식을 시작할 수 없습니다. 종료 후 다시 시도해 주세요."
      setStateValue("status", "start-error")
    }
  }

  stopButton.onclick = () => {
    if (state.recognition) {
      try {
        state.recognition.stop()
      } catch (error) {
        statusElement.textContent = "현재 녹음 중이 아닙니다."
      }
    }
  }
  cancelButton.onclick = () => {
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel()
      statusElement.textContent = "음성 재생을 중지했습니다."
    }
  }

  const renderVoices = () => {
    if (!window.speechSynthesis) return
    const voices = window.speechSynthesis.getVoices().map((voice) => ({
      name: voice.name,
      lang: voice.lang,
      uri: voice.voiceURI
    }))
    const encoded = JSON.stringify(voices)
    if (encoded !== state.lastVoices) {
      state.lastVoices = encoded
      setStateValue("voices", voices)
    }
  }

  if (window.speechSynthesis) {
    window.speechSynthesis.onvoiceschanged = renderVoices
    renderVoices()
  }

  const settings = data || {}
  answersElement.replaceChildren()
  ;(settings.answers || []).forEach((answer, index) => {
    const button = document.createElement("button")
    button.type = "button"
    button.textContent = "🔊 답변 " + (index + 1) + " 음성 재생"
    button.setAttribute("aria-label", "답변 " + (index + 1) + " 전체 음성 재생")
    button.onclick = () => {
      if (!window.speechSynthesis) {
        statusElement.textContent = "이 브라우저는 음성 합성을 지원하지 않습니다."
        return
      }
      window.speechSynthesis.cancel()
      const utterance = new SpeechSynthesisUtterance(answer)
      utterance.lang = "ko-KR"
      utterance.rate = Number(settings.rate || 1)
      utterance.volume = Number(settings.volume ?? 1)
      const voices = window.speechSynthesis.getVoices()
      const selected = voices.find((voice) => voice.voiceURI === settings.voice)
      if (selected) utterance.voice = selected
      utterance.onstart = () => { statusElement.textContent = "답변을 읽고 있습니다." }
      utterance.onend = () => { statusElement.textContent = "음성 재생이 끝났습니다." }
      utterance.onerror = () => { statusElement.textContent = "음성 재생에 실패했습니다. 텍스트 답변을 확인해 주세요." }
      window.speechSynthesis.speak(utterance)
    }
    answersElement.appendChild(button)
  })

  return () => {
    if (window.speechSynthesis) window.speechSynthesis.onvoiceschanged = null
  }
}
"""

SPEECH_COMPONENT = st.components.v2.component(
    "hangyeol_inline_speech",
    html=SPEECH_HTML,
    js=SPEECH_JS,
)


class UserFacingError(Exception):
    pass


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UserFacingError("숫자만 계산할 수 있습니다.")
    if not math.isfinite(value) or abs(value) > 1e100:
        raise UserFacingError("계산 결과가 허용 범위를 벗어났습니다.")
    return value


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _evaluate_expression(node, depth=0):
    if depth > 20:
        raise UserFacingError("계산식이 너무 복잡합니다.")
    if isinstance(node, ast.Expression):
        return _evaluate_expression(node.body, depth + 1)
    if isinstance(node, ast.Constant):
        return _number(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_expression(node.left, depth + 1)
        right = _evaluate_expression(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise UserFacingError("지수는 -100부터 100 사이에서만 계산할 수 있습니다.")
        return _number(_BINARY_OPERATORS[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _number(_UNARY_OPERATORS[type(node.op)](_evaluate_expression(node.operand, depth + 1)))
    raise UserFacingError("사칙연산, 괄호, 나머지, 거듭제곱만 계산할 수 있습니다.")


def calculate(expression):
    expression = expression.strip()
    if not expression or len(expression) > 160 or not re.fullmatch(r"[0-9eE.+\-*/()%\s]+", expression):
        raise UserFacingError("계산식은 숫자와 +, -, *, /, //, %, **, 괄호만 사용해 주세요.")
    try:
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 40:
            raise UserFacingError("계산식이 너무 복잡합니다.")
        result = _evaluate_expression(tree)
    except (SyntaxError, ZeroDivisionError, OverflowError, ValueError):
        raise UserFacingError("계산식을 확인해 주세요. 0으로 나누거나 너무 큰 수는 계산할 수 없습니다.") from None
    return f"계산 결과: **{result:g}**"


_UNIT_DEFINITIONS = {
    "m": ("length", 1.0, 0.0, "m"),
    "meter": ("length", 1.0, 0.0, "m"),
    "meters": ("length", 1.0, 0.0, "m"),
    "미터": ("length", 1.0, 0.0, "m"),
    "km": ("length", 1000.0, 0.0, "m"),
    "kilometer": ("length", 1000.0, 0.0, "m"),
    "kilometers": ("length", 1000.0, 0.0, "m"),
    "킬로미터": ("length", 1000.0, 0.0, "m"),
    "cm": ("length", 0.01, 0.0, "m"),
    "센티미터": ("length", 0.01, 0.0, "m"),
    "mm": ("length", 0.001, 0.0, "m"),
    "밀리미터": ("length", 0.001, 0.0, "m"),
    "mi": ("length", 1609.344, 0.0, "m"),
    "mile": ("length", 1609.344, 0.0, "m"),
    "miles": ("length", 1609.344, 0.0, "m"),
    "마일": ("length", 1609.344, 0.0, "m"),
    "ft": ("length", 0.3048, 0.0, "m"),
    "feet": ("length", 0.3048, 0.0, "m"),
    "피트": ("length", 0.3048, 0.0, "m"),
    "in": ("length", 0.0254, 0.0, "m"),
    "inch": ("length", 0.0254, 0.0, "m"),
    "inches": ("length", 0.0254, 0.0, "m"),
    "인치": ("length", 0.0254, 0.0, "m"),
    "kg": ("mass", 1.0, 0.0, "kg"),
    "kilogram": ("mass", 1.0, 0.0, "kg"),
    "킬로그램": ("mass", 1.0, 0.0, "kg"),
    "g": ("mass", 0.001, 0.0, "kg"),
    "gram": ("mass", 0.001, 0.0, "kg"),
    "그램": ("mass", 0.001, 0.0, "kg"),
    "mg": ("mass", 0.000001, 0.0, "kg"),
    "밀리그램": ("mass", 0.000001, 0.0, "kg"),
    "lb": ("mass", 0.45359237, 0.0, "kg"),
    "lbs": ("mass", 0.45359237, 0.0, "kg"),
    "pound": ("mass", 0.45359237, 0.0, "kg"),
    "파운드": ("mass", 0.45359237, 0.0, "kg"),
    "l": ("volume", 1.0, 0.0, "L"),
    "liter": ("volume", 1.0, 0.0, "L"),
    "litre": ("volume", 1.0, 0.0, "L"),
    "리터": ("volume", 1.0, 0.0, "L"),
    "ml": ("volume", 0.001, 0.0, "L"),
    "밀리리터": ("volume", 0.001, 0.0, "L"),
    "c": ("temperature", 1.0, 273.15, "°C"),
    "°c": ("temperature", 1.0, 273.15, "°C"),
    "섭씨": ("temperature", 1.0, 273.15, "°C"),
    "f": ("temperature", 5 / 9, 273.15 - 32 * 5 / 9, "°F"),
    "°f": ("temperature", 5 / 9, 273.15 - 32 * 5 / 9, "°F"),
    "화씨": ("temperature", 5 / 9, 273.15 - 32 * 5 / 9, "°F"),
    "k": ("temperature", 1.0, 0.0, "K"),
    "kelvin": ("temperature", 1.0, 0.0, "K"),
    "켈빈": ("temperature", 1.0, 0.0, "K"),
}
_UNIT_PATTERN = re.compile(
    r"([-+]?\d+(?:\.\d+)?)\s*([A-Za-z가-힣°]+)\s*(?:to|->|→|에서|를)\s*([A-Za-z가-힣°]+)",
    re.IGNORECASE,
)


def convert_units(prompt):
    match = _UNIT_PATTERN.search(prompt)
    if not match:
        raise UserFacingError("예: `10 km to mi`, `25°C를 화씨로`처럼 숫자·단위·목표 단위를 함께 적어 주세요.")
    amount = float(match.group(1))
    source = match.group(2).lower()
    target = match.group(3).lower()
    for suffix in ("으로", "로"):
        if target.endswith(suffix):
            target = target[: -len(suffix)]
            break
    source_unit = _UNIT_DEFINITIONS.get(source)
    target_unit = _UNIT_DEFINITIONS.get(target)
    if not source_unit or not target_unit or source_unit[0] != target_unit[0]:
        raise UserFacingError("지원하는 같은 종류의 단위끼리 변환해 주세요. 길이·무게·부피·온도 단위를 지원합니다.")
    base_value = amount * source_unit[1] + source_unit[2]
    converted = (base_value - target_unit[2]) / target_unit[1]
    target_symbols = {
        "km": "km", "cm": "cm", "mm": "mm", "mi": "mi", "ft": "ft", "in": "in",
        "kilometer": "km", "kilometers": "km", "킬로미터": "km",
        "centimeter": "cm", "센티미터": "cm", "millimeter": "mm", "밀리미터": "mm",
        "mile": "mi", "miles": "mi", "마일": "mi",
        "feet": "ft", "피트": "ft", "inch": "in", "inches": "in", "인치": "in",
        "gram": "g", "그램": "g", "milligram": "mg", "밀리그램": "mg",
        "pound": "lb", "pounds": "lb", "파운드": "lb",
        "liter": "L", "litre": "L", "리터": "L", "밀리리터": "mL",
    }
    return f"변환 결과: **{converted:.6g} {target_symbols.get(target, target_unit[3])}**"


def _time_reply(prompt):
    requested_zone = None
    time_zones = {
        "서울": ("Asia/Seoul", "서울"),
        "한국": ("Asia/Seoul", "한국"),
        "도쿄": ("Asia/Tokyo", "도쿄"),
        "런던": ("Europe/London", "런던"),
        "뉴욕": ("America/New_York", "뉴욕"),
        "로스앤젤레스": ("America/Los_Angeles", "로스앤젤레스"),
    }
    for label, (zone, display) in time_zones.items():
        if label in prompt:
            requested_zone = (zone, display)
            break
    if requested_zone:
        now = datetime.now(ZoneInfo(requested_zone[0]))
        location = f"{requested_zone[1]} ({requested_zone[0]})"
    elif any(token in prompt for token in ("현지 시간", "이 기기 시간", "내 시간")):
        now = datetime.now().astimezone()
        location = f"이 기기의 현지 시간대 ({now.tzname() or now.tzinfo})"
    else:
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        location = "한국 (Asia/Seoul)"
    weekdays = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")
    return f"현재 **{location}** 기준은 **{now:%Y년 %m월 %d일} {weekdays[now.weekday()]} {now:%H:%M:%S}**입니다."


_WEATHER_CODES = {
    0: "맑음", 1: "대체로 맑음", 2: "부분적으로 흐림", 3: "흐림",
    45: "안개", 48: "착빙 안개", 51: "약한 이슬비", 53: "이슬비",
    55: "강한 이슬비", 56: "약한 어는 이슬비", 57: "강한 어는 이슬비",
    61: "약한 비", 63: "비", 65: "강한 비", 66: "약한 어는 비",
    67: "강한 어는 비", 71: "약한 눈", 73: "눈", 75: "강한 눈",
    77: "싸락눈", 80: "약한 소나기", 81: "소나기", 82: "강한 소나기",
    85: "약한 눈 소나기", 86: "강한 눈 소나기", 95: "뇌우",
    96: "약한 우박을 동반한 뇌우", 99: "강한 우박을 동반한 뇌우",
}
_KOREAN_CITY_ALIASES = {
    "서울": "Seoul", "서울시": "Seoul", "서울특별시": "Seoul",
    "부산": "Busan", "부산시": "Busan", "부산광역시": "Busan",
    "인천": "Incheon", "인천시": "Incheon", "인천광역시": "Incheon",
    "대구": "Daegu", "대전": "Daejeon", "광주": "Gwangju", "울산": "Ulsan",
    "세종": "Sejong", "제주": "Jeju", "제주시": "Jeju",
    "강릉": "Gangneung", "춘천": "Chuncheon", "수원": "Suwon",
    "청주": "Cheongju", "전주": "Jeonju", "포항": "Pohang",
}


def current_weather(place):
    place = place.strip()
    if not place:
        raise UserFacingError("사이드바의 날씨 지역을 입력해 주세요.")
    if len(place) > 100:
        raise UserFacingError("날씨 지역은 100자 이내로 입력해 주세요.")
    query_place = _KOREAN_CITY_ALIASES.get(place, place)
    try:
        geocoding_response = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": query_place, "count": 5, "language": "ko", "format": "json"},
            timeout=10,
        )
        geocoding_response.raise_for_status()
        locations = geocoding_response.json().get("results") or []
        if not locations:
            raise UserFacingError(f"‘{place}’ 지역을 찾지 못했습니다. 더 구체적인 도시나 지역명을 입력해 주세요.")
        if len(locations) > 1:
            is_known_korean_city = (
                place in _KOREAN_CITY_ALIASES
                or query_place.lower() in {item.lower() for item in _KOREAN_CITY_ALIASES.values()}
            )
            korean_matches = [item for item in locations if item.get("country_code") == "KR"]
            if is_known_korean_city and len(korean_matches) == 1:
                location = korean_matches[0]
            else:
                normalized_query = query_place.casefold()
                exact_matches = [
                    item for item in locations
                    if str(item.get("name", "")).casefold() == normalized_query
                ]
                if len(exact_matches) == 1:
                    location = exact_matches[0]
                else:
                    candidates = ", ".join(
                        f"{item.get('name', '')}{', ' + item['admin1'] if item.get('admin1') else ''}{', ' + item.get('country', '')}"
                        for item in locations[:4]
                    )
                    raise UserFacingError(
                        f"‘{place}’ 검색 결과가 여러 곳입니다({candidates}). 시·도나 국가를 덧붙여 다시 입력해 주세요."
                    )
        else:
            location = locations[0]
        weather_response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
            timeout=10,
        )
        weather_response.raise_for_status()
        payload = weather_response.json()
    except requests.RequestException:
        raise UserFacingError("날씨 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.") from None
    except (KeyError, TypeError, ValueError):
        raise UserFacingError("날씨 서비스 응답을 읽을 수 없습니다. 잠시 후 다시 시도해 주세요.") from None

    current = payload.get("current", {})
    units = payload.get("current_units", {})
    weather_description = _WEATHER_CODES.get(current.get("weather_code"), "알 수 없음")
    location_name = location.get("name", place)
    region_parts = [
        value for value in (location.get("admin1"), location.get("country"))
        if value and value != location_name
    ]
    region = ", ".join(region_parts)
    suffix = f", {region}" if region else ""
    return (
        f"**{location_name}{suffix} 현재 날씨** (Open-Meteo, 기준 시각 {current.get('time', '정보 없음')})\n\n"
        f"- 상태: {weather_description}\n"
        f"- 기온: {current.get('temperature_2m', '정보 없음')} {units.get('temperature_2m', '°C')}\n"
        f"- 체감 기온: {current.get('apparent_temperature', '정보 없음')} {units.get('apparent_temperature', '°C')}\n"
        f"- 습도: {current.get('relative_humidity_2m', '정보 없음')} {units.get('relative_humidity_2m', '%')}\n"
        f"- 강수량: {current.get('precipitation', '정보 없음')} {units.get('precipitation', 'mm')}\n"
        f"- 풍속: {current.get('wind_speed_10m', '정보 없음')} {units.get('wind_speed_10m', 'km/h')}"
    )


def route_tool(prompt, place):
    lowered = prompt.lower()
    if any(token in lowered for token in ("단위 변환", "단위 환산", "변환해", "환산해")) or _UNIT_PATTERN.search(prompt):
        if _UNIT_PATTERN.search(prompt):
            return convert_units(prompt)
        if any(token in lowered for token in ("단위 변환", "단위 환산", "변환해", "환산해")):
            return convert_units(prompt)
    if any(token in prompt for token in ("날씨", "기온", "강수", "비 와", "비가 와", "눈 와")):
        return current_weather(place)
    if any(token in prompt for token in (
        "현재 시간", "한국 시간", "서울 시간", "현지 시간", "이 기기 시간", "내 시간",
        "지금 몇 시", "몇 시", "시간이 몇", "오늘 날짜", "현재 시각", "지금 시각", "시간 알려",
    )):
        return _time_reply(prompt)
    calc_match = re.search(r"계산(?:해줘|해|해 주세요)?\s*[:：]?\s*(.+)", prompt)
    if calc_match:
        expression = calc_match.group(1).strip().rstrip("=? ")
        return calculate(expression)
    candidate = re.sub(r"(?:계산해줘|계산해|계산|얼마야|얼마인가요|알려줘|계산해 주세요)", "", prompt)
    candidate = candidate.strip().rstrip("=? ")
    if re.fullmatch(r"[0-9eE.+\-*/()%\s]+", candidate) and re.search(r"\d", candidate):
        return calculate(candidate)
    return None


def _groq_reply(prompt, api_key, model, max_tokens):
    if not api_key:
        raise UserFacingError("app.py 상단의 GROQ_API_KEY에 Groq API 키를 입력한 뒤 앱을 다시 실행해 주세요.")
    from groq import (
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        AuthenticationError,
        BadRequestError,
        Groq,
        RateLimitError,
    )

    recent_messages = st.session_state.messages[-MAX_HISTORY_MESSAGES:]
    api_messages = [
        {
            "role": "system",
            "content": (
                "당신은 친절한 한국어 중심 개인 비서입니다. 사용자의 질문에 정확하고 자연스럽게 답하고, "
                "불확실한 사실은 불확실하다고 밝힙니다. 번역 요청은 요청한 언어로 번역합니다. "
                "실시간 시간·날씨·계산 결과를 추측하지 말고, 제공된 도구 결과가 없으면 그 한계를 알립니다. "
                "대화 요약은 실제 제공된 대화 내용에 근거합니다."
            ),
        },
        *recent_messages,
        {"role": "user", "content": prompt},
    ]
    try:
        client = Groq(api_key=api_key, timeout=30.0, max_retries=0)
        response = client.chat.completions.create(
            model=model,
            messages=api_messages,
            max_completion_tokens=max_tokens,
        )
    except AuthenticationError:
        raise UserFacingError("Groq API 키 인증에 실패했습니다. 키를 확인해 주세요.") from None
    except RateLimitError:
        raise UserFacingError("Groq 요청 한도에 도달했습니다. 잠시 기다린 뒤 다시 시도해 주세요.") from None
    except APITimeoutError:
        raise UserFacingError("Groq 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.") from None
    except APIConnectionError:
        raise UserFacingError("Groq 서비스에 연결하지 못했습니다. 네트워크를 확인한 뒤 다시 시도해 주세요.") from None
    except BadRequestError:
        raise UserFacingError("Groq 요청을 처리하지 못했습니다. 모델 이름이나 질문 내용을 확인해 주세요.") from None
    except APIStatusError:
        raise UserFacingError("Groq 서비스에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.") from None
    answer = response.choices[0].message.content if response.choices else None
    if not answer:
        raise UserFacingError("AI가 빈 답변을 반환했습니다. 질문을 바꾸어 다시 시도해 주세요.")
    return answer


def process_prompt(prompt):
    prompt = prompt.strip()
    if not prompt:
        st.session_state.pending_error = "질문을 입력해 주세요."
        return False
    if len(prompt) > MAX_PROMPT_CHARS:
        st.session_state.pending_prompt = prompt
        st.session_state.pending_error = f"질문은 {MAX_PROMPT_CHARS}자 이내로 입력해 주세요."
        return False
    try:
        answer = route_tool(prompt, st.session_state.weather_place)
        if answer is None:
            answer = _groq_reply(
                prompt,
                GROQ_API_KEY,
                st.session_state.model,
                st.session_state.max_tokens,
            )
    except UserFacingError as error:
        st.session_state.pending_prompt = prompt
        st.session_state.pending_error = str(error)
        return False

    st.session_state.messages.extend(
        ({"role": "user", "content": prompt}, {"role": "assistant", "content": answer})
    )
    st.session_state.messages = st.session_state.messages[-MAX_HISTORY_MESSAGES:]
    st.session_state.pending_prompt = None
    st.session_state.pending_error = None
    return True


for state_key, default in (
    ("messages", []),
    ("pending_prompt", None),
    ("pending_error", None),
    ("weather_place", "서울"),
    ("model", DEFAULT_MODEL),
    ("max_tokens", 2048),
    ("voice_draft", ""),
    ("voice_draft_revision", 0),
    ("consumed_transcript_id", None),
    ("pending_version", 0),
):
    if state_key not in st.session_state:
        st.session_state[state_key] = default


speech_state = st.session_state.get(SPEECH_KEY, {})
if not isinstance(speech_state, dict):
    speech_state = {}
transcript_event = speech_state.get("transcript")
if isinstance(transcript_event, dict) and transcript_event.get("id") != st.session_state.consumed_transcript_id:
    st.session_state.consumed_transcript_id = transcript_event.get("id")
    st.session_state.voice_draft = str(transcript_event.get("text", ""))[:MAX_PROMPT_CHARS]
    st.session_state.voice_draft_revision += 1


def clear_conversation():
    st.session_state.messages = []
    st.session_state.pending_prompt = None
    st.session_state.pending_error = None
    st.session_state.voice_draft = ""
    st.session_state.voice_draft_revision += 1
    st.session_state.pending_version += 1
    current_speech_state = st.session_state.get(SPEECH_KEY, {})
    if isinstance(current_speech_state, dict):
        current_event = current_speech_state.get("transcript")
        if isinstance(current_event, dict):
            st.session_state.consumed_transcript_id = current_event.get("id")


with st.sidebar:
    st.header("설정")
    st.caption("코드의 GROQ_API_KEY: " + ("설정됨" if GROQ_API_KEY else "미설정"))
    st.text_input("모델", key="model", help="기본 모델: openai/gpt-oss-120b")
    st.slider("최대 답변 길이(토큰)", min_value=256, max_value=4096, step=256, key="max_tokens")
    st.text_input("날씨 지역", key="weather_place", max_chars=100, help="예: 서울, 부산, 춘천")

    voices = speech_state.get("voices", [])
    usable_voices = [
        item for item in voices
        if isinstance(item, dict) and isinstance(item.get("uri"), str)
    ]
    voice_map = {item["uri"]: item for item in usable_voices}
    voice_options = [""] + list(voice_map)
    selected_voice = st.selectbox(
        "브라우저 TTS 목소리",
        options=voice_options,
        format_func=lambda uri: (
            "브라우저 기본 한국어 목소리"
            if not uri
            else f"{voice_map[uri].get('name', '목소리')} ({voice_map[uri].get('lang', '')})"
        ),
        key="tts_voice",
        help="목소리 목록은 현재 브라우저가 제공하는 음성에 따라 달라집니다.",
    )
    tts_rate = st.slider("음성 속도", min_value=0.5, max_value=2.0, value=1.0, step=0.1)
    tts_volume = st.slider("음성 음량", min_value=0.0, max_value=1.0, value=1.0, step=0.1)
    if st.button("대화 초기화", icon=":material/delete_sweep:", width="stretch"):
        clear_conversation()
        st.rerun()

    st.divider()
    st.caption(
        "대화 기록은 이 세션 안에서만 유지됩니다. 일반 질문과 대화 문맥은 Groq로, "
        "날씨 조회 시 지역명은 Open-Meteo로 전송됩니다. 이 앱은 별도 데이터베이스를 사용하지 않습니다."
    )


st.title("한결 · AI 비서")
st.caption("한국어로 편하게 질문해 주세요. 시간·날씨·계산은 도구로 확인합니다.")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if st.session_state.pending_prompt is not None:
    with st.chat_message("user"):
        st.markdown(st.session_state.pending_prompt)
    if st.session_state.pending_error:
        st.warning(st.session_state.pending_error)
    pending_key = f"pending_editor_{st.session_state.pending_version}"
    with st.form("retry_prompt_form", clear_on_submit=False):
        st.text_area(
            "전송되지 않은 질문 (수정 후 다시 시도할 수 있어요)",
            value=st.session_state.pending_prompt,
            key=pending_key,
            height=110,
        )
        retry = st.form_submit_button("질문 다시 보내기", type="primary")
    if retry:
        st.session_state.pending_prompt = st.session_state[pending_key]
        st.session_state.pending_version += 1
        with st.spinner("답변을 준비하고 있습니다..."):
            process_prompt(st.session_state.pending_prompt)
        st.rerun()

if st.session_state.voice_draft:
    st.subheader("음성 입력 확인")
    st.caption("인식된 내용을 직접 수정한 뒤에만 전송됩니다.")
    voice_key = f"voice_editor_{st.session_state.voice_draft_revision}"
    with st.form("voice_transcript_form", clear_on_submit=False):
        st.text_area(
            "인식 결과",
            value=st.session_state.voice_draft,
            key=voice_key,
            max_chars=MAX_PROMPT_CHARS,
            height=110,
        )
        send_voice = st.form_submit_button(
            "확인한 음성 질문 전송",
            type="primary",
            disabled=speech_state.get("status") == "listening",
        )
    if send_voice:
        voice_prompt = st.session_state[voice_key]
        st.session_state.voice_draft = ""
        st.session_state.voice_draft_revision += 1
        st.session_state.pending_version += 1
        st.session_state.pending_prompt = voice_prompt
        st.session_state.pending_error = None
        with st.spinner("답변을 준비하고 있습니다..."):
            process_prompt(voice_prompt)
        st.rerun()

if st.session_state.pending_prompt is None:
    submitted_prompt = st.chat_input(
        "메시지를 입력하세요",
        max_chars=MAX_PROMPT_CHARS,
        disabled=False,
    )
    if submitted_prompt:
        st.session_state.pending_prompt = submitted_prompt
        st.session_state.pending_error = None
        st.session_state.pending_version += 1
        with st.spinner("답변을 준비하고 있습니다..."):
            process_prompt(submitted_prompt)
        st.rerun()
else:
    st.chat_input("먼저 전송되지 않은 질문을 수정하거나 다시 보내세요", disabled=True)

speech_state = SPEECH_COMPONENT(
    key=SPEECH_KEY,
    data={
        "answers": [
            message["content"]
            for message in st.session_state.messages
            if message["role"] == "assistant"
        ],
        "voice": selected_voice,
        "rate": tts_rate,
        "volume": tts_volume,
    },
    on_transcript_change=lambda: None,
    on_status_change=lambda: None,
    on_voices_change=lambda: None,
)

browser_status = speech_state.status if hasattr(speech_state, "status") else None
if browser_status and browser_status not in ("listening", "complete"):
    st.caption(str(browser_status))
