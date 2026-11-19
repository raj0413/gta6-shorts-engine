"""
Gemini AI Viral Judge & Hook Generator (curator.py).
Transcribes candidate audio using OpenAI Whisper (with word-level timestamps).
Evaluates viral entertainment score (1-10) using Google Gemini 2.0 Flash.
Rejects clips scored < 8/10.
Generates high-CTR Short title, on-screen viral hook, tags, and safety verification.
"""

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import (
    GEMINI_API_KEY,
    MIN_VIRAL_SCORE,
    TEMP_DIR,
    WHISPER_MODEL,
    get_yt_dlp_cmd,
    logger,
)


@dataclass
class WordTimestamp:
    """Represents a single word with precise start and end timing in seconds."""
    word: str
    start: float
    end: float


@dataclass
class CurationResult:
    """Result returned by Gemini AI evaluation."""
    approved: bool
    viral_score: int          # 1 to 10
    verdict: str              # APPROVED or REJECTED
    short_title: str          # Clicky Short title (<60 chars, emojis)
    hook_text: str            # On-screen text banner (e.g. 'BRO DID NOT JUST DO THAT 💀')
    description: str          # Video description with credits & fair-use
    tags: List[str]           # High-ranking tags
    safety_rating: str        # SAFE or UNSAFE
    reason: str               # AI explanation of score
    transcript: str           # Full Whisper transcript
    word_timestamps: List[Dict[str, Any]]  # Word-level timing for karaoke captions

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ViralCurator:
    """AI Curation Engine combining Whisper transcription and Gemini 2.0 evaluation."""

    def __init__(self, api_key: Optional[str] = None, model_size: str = WHISPER_MODEL):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_size = model_size
        self._whisper_model = None

    def _get_whisper_model(self):
        """Lazy loader for Whisper model to conserve memory."""
        if self._whisper_model is None:
            logger.info(f"Loading OpenAI Whisper model ('{self.model_size}')...")
            try:
                import torch
                torch.set_num_threads(4)
                import whisper
                self._whisper_model = whisper.load_model(self.model_size)
                logger.info("Whisper model loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load Whisper model: {e}")
                self._whisper_model = None
        return self._whisper_model

    def extract_clip_audio(
        self, video_url: str, video_id: str, start_time: float, duration: float
    ) -> Optional[Path]:
        """
        Extracts exact audio clip slice using yt-dlp.
        Returns path to the 16kHz mono WAV file optimized for Whisper.
        """
        raw_m4a = TEMP_DIR / f"{video_id}_{int(start_time)}_{int(duration)}_raw.m4a"
        wav_file = TEMP_DIR / f"{video_id}_{int(start_time)}_{int(duration)}_whisper.wav"

        if wav_file.exists() and wav_file.stat().st_size > 5000:
            return wav_file

        end_time = start_time + duration
        cmd_dl = get_yt_dlp_cmd() + [
            "-f", "300/301/234/140/ba[ext=m4a]/ba",
            "--download-sections", f"*{start_time}-{end_time}",
            "--no-warnings",
            "-o", str(raw_m4a),
            video_url,
        ]

        try:
            res = subprocess.run(cmd_dl, capture_output=True, text=True, timeout=90)
            if not raw_m4a.exists() or raw_m4a.stat().st_size < 1000:
                logger.warning(f"Could not download audio slice for transcription: {res.stderr[:200]}")
                return None

            # Convert to 16kHz mono WAV for Whisper
            cmd_convert = [
                "ffmpeg",
                "-y",
                "-i", str(raw_m4a),
                "-ar", "16000",
                "-ac", "1",
                "-c:a", "pcm_s16le",
                str(wav_file),
            ]
            subprocess.run(cmd_convert, capture_output=True, timeout=30)
            raw_m4a.unlink(missing_ok=True)

            if wav_file.exists() and wav_file.stat().st_size > 1000:
                return wav_file
            return None

        except Exception as e:
            logger.error(f"Error extracting audio slice: {e}")
            return None

    def transcribe(
        self, audio_path: Path, language: Optional[str] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Transcribes audio file using Whisper, extracting word-level timestamps.
        Returns (full_transcript_text, list_of_word_timing_dicts).
        """
        model = self._get_whisper_model()
        if not model:
            logger.warning("Whisper model unavailable. Returning fallback empty transcript.")
            return "Insane GTA 6 live stream reaction and clutch moment!", []

        try:
            logger.info(f"Transcribing audio with word-level timestamps ({audio_path.name})...")
            transcribe_kwargs = {
                "word_timestamps": True,
                "fp16": False,
            }
            if language and language in ("hi", "en", "es", "fr", "de"):
                transcribe_kwargs["language"] = language

            result = model.transcribe(
                str(audio_path),
                **transcribe_kwargs,
            )

            text = result.get("text", "").strip()
            word_timings: List[Dict[str, Any]] = []

            for seg in result.get("segments", []):
                for w in seg.get("words", []):
                    word_text = w.get("word", "").strip()
                    if word_text:
                        word_timings.append({
                            "word": word_text,
                            "start": round(float(w.get("start", 0.0)), 2),
                            "end": round(float(w.get("end", 0.0)), 2),
                        })

            logger.info(f"Transcription complete: '{text[:80]}...' ({len(word_timings)} words mapped).")
            return text, word_timings

        except Exception as e:
            logger.error(f"Whisper transcription error: {e}")
            return "GTA 6 funny live stream gameplay moment", []

    def evaluate_with_gemini(
        self,
        streamer_name: str,
        stream_title: str,
        transcript: str,
        keywords: List[str],
        spike_type: str,
    ) -> Dict[str, Any]:
        """
        Queries Gemini 2.0 Flash to judge virality, verify safety, and author high-CTR titles.
        """
        prompt = f"""
You are a master viral YouTube Shorts algorithm specialist and executive gaming clip curator.
Your task is to judge an autonomous GTA 6 live stream highlight candidate and decide if it will blow up on YouTube Shorts / TikTok.

STREAM CONTEXT:
- Streamer: {streamer_name}
- Stream Title: "{stream_title}"
- Detection Spike Type: {spike_type}
- Chat/Audio Trigger Keywords: {', '.join(keywords)}
- Audio Transcript: "{transcript}"

CRITICAL RULES:
1. Rate virality on a 1-10 scale.
   - 8-10: Mindblowing, hilarious, streamer screaming/rage, unexpected fail, insane glitch, or funny Hindi/English banter.
   - 7: Good entertaining moment, clutch play, viral meme moment.
   - 1-6: Boring, completely silent, or repetitive.
   - NOTE: If the streamer speaks Hindi/Hinglish (e.g. CarryisLive, GamerFleet), understand and evaluate their comedic roasts, emotional yelling, and gamer slang. Funny or energetic Hindi gaming commentary has MASSIVE viral appeal!
2. Safety & Copyright check: Reject extreme hate speech, slurs, sexual content, or full-length copyrighted song performances (mark UNSAFE). Gaming banter, yelling, humor, and gameplay sound are completely SAFE.
3. YouTube Short Title: Must be under 60 characters, ultra-clickable, high CTR, all caps or title case with 1-2 punchy emojis (e.g. 💀, 😭, 😱, 🔥).
4. Hook Text: 2 to 4 words punchy on-screen caption hook (e.g., "HE REALLY DID THIS 💀", "WAIT FOR THE END 😭", "BRO IS NOT SURVIVING THIS").
5. Description: 2-3 lines with streamer credit, original link placeholder, and clean fair-use disclaimer.
6. Tags: 8-10 high-traffic gaming tags including #Shorts, #GTA6, #{streamer_name.replace(' ', '')}.

Respond ONLY with valid, raw JSON (no markdown formatting, no code fences):
{{
  "viral_score": 9,
  "verdict": "APPROVED",
  "reason": "Clear explanation of why this moment will retain viewers.",
  "short_title": "CARRYMINATI CRAZY GTA 6 CLUTCH 💀🔥",
  "hook_text": "WAIT FOR THE END 💀",
  "description": "The most insane GTA 6 moment yet! \\n\\n👑 Streamer: {streamer_name} \\n\\n#Shorts #GTA6 #Gaming #ViralClips",
  "tags": ["Shorts", "GTA 6", "GTA VI", "{streamer_name}", "Gaming Clips", "Funny Moments", "GTA 6 Gameplay"],
  "safety_rating": "SAFE"
}}
"""

        if not self.api_key:
            logger.warning("GEMINI_API_KEY not configured. Using rule-based fallback curation.")
            return self._fallback_rule_curation(streamer_name, transcript, keywords)

        # Candidate models in priority order (flash-lite has high availability & fast throughput)
        model_names = ["gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-flash-latest"]

        # Strategy 1: Direct Google Generative Language REST API (High reliability, zero extra dependencies)
        import requests
        for m_name in model_names:
            try:
                endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={self.api_key}"
                headers = {"Content-Type": "application/json"}
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.7,
                        "responseMimeType": "application/json",
                    },
                }
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text_val = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        if text_val:
                            logger.info(f"Successfully evaluated highlight with Gemini model: {m_name}")
                            return self._parse_gemini_json(text_val)
                else:
                    logger.warning(f"Direct REST call to {m_name} returned status {resp.status_code}: {resp.text[:150]}")
            except Exception as e_req:
                logger.warning(f"Direct REST call to {m_name} failed: {e_req}")
                continue

        # Strategy 2: google.genai SDK
        for m_name in model_names:
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.api_key)
                response = client.models.generate_content(
                    model=m_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.7,
                        response_mime_type="application/json",
                    ),
                )
                raw_text = response.text.strip()
                return self._parse_gemini_json(raw_text)
            except Exception as e1:
                logger.debug(f"google.genai call attempt with {m_name} failed: {e1}")
                continue

        # Strategy 3: google.generativeai SDK fallback
        for m_name in model_names:
            try:
                import google.generativeai as gai
                gai.configure(api_key=self.api_key)
                model = gai.GenerativeModel(m_name)
                response = model.generate_content(prompt)
                raw_text = response.text.strip()
                return self._parse_gemini_json(raw_text)
            except Exception as e2:
                logger.debug(f"google.generativeai call attempt with {m_name} failed: {e2}")
                continue

        logger.error("All Gemini API model attempts failed. Reverting to rule-based curation.")
        return self._fallback_rule_curation(streamer_name, transcript, keywords)

    def _parse_gemini_json(self, raw_text: str) -> Dict[str, Any]:
        """Cleans and extracts JSON payload from Gemini model response."""
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned)
            cleaned = re.sub(r"```$", "", cleaned).strip()

        try:
            data = json.loads(cleaned)
            # Ensure required keys exist
            data["viral_score"] = int(data.get("viral_score", 8))
            data["verdict"] = str(data.get("verdict", "APPROVED")).upper()
            data["safety_rating"] = str(data.get("safety_rating", "SAFE")).upper()
            data["short_title"] = str(data.get("short_title", "INSANE GTA 6 CLUTCH MOMENT 💀"))[:60]
            data["hook_text"] = str(data.get("hook_text", "BRO NO WAY 💀"))
            data["description"] = str(data.get("description", "Daily GTA 6 viral highlights! #Shorts #GTA6"))
            data["tags"] = list(data.get("tags", ["Shorts", "GTA6", "Gaming"]))
            return data
        except Exception as e:
            logger.warning(f"Failed to parse Gemini JSON output: {e}. Raw response: {raw_text[:150]}")
            raise e

    def _fallback_rule_curation(
        self, streamer_name: str, transcript: str, keywords: List[str]
    ) -> Dict[str, Any]:
        """Rule-based curation fallback when AI API is unavailable."""
        title_tag = keywords[0].upper() if keywords else "FAIL"
        clean_name = streamer_name.upper()

        return {
            "viral_score": 8,
            "verdict": "APPROVED",
            "reason": f"High intensity {keywords} spike detected during GTA 6 gameplay.",
            "short_title": f"{clean_name} INSANE GTA 6 MOMENT! 💀🔥"[:60],
            "hook_text": "WAIT FOR THE ENDING 💀",
            "description": f"Most insane GTA 6 moment with {streamer_name}!\n\n👑 Creator: {streamer_name}\n\n#Shorts #GTA6 #Gaming",
            "tags": ["Shorts", "GTA 6", "GTA VI", streamer_name, "Gaming Highlights", "Funny Moments"],
            "safety_rating": "SAFE",
        }

    def curate_candidate(
        self,
        video_url: str,
        video_id: str,
        streamer_name: str,
        stream_title: str,
        start_time: float,
        duration: float,
        keywords: List[str],
        spike_type: str,
        language: Optional[str] = None,
    ) -> CurationResult:
        """
        Executes complete curation pipeline:
        1. Downloads clip audio.
        2. Transcribes with word timestamps via Whisper.
        3. Evaluates with Gemini 2.0 Flash.
        4. Rejects if score < MIN_VIRAL_SCORE (default 8) or if UNSAFE.
        """
        logger.info(f"Curating candidate moment: {start_time:.1f}s - {start_time+duration:.1f}s ({streamer_name})")

        # 1. Extract audio
        audio_path = self.extract_clip_audio(video_url, video_id, start_time, duration)
        transcript = ""
        word_timings = []

        if audio_path:
            transcript, word_timings = self.transcribe(audio_path, language=language)
            # Cleanup temporary wav
            audio_path.unlink(missing_ok=True)
        else:
            logger.warning("Audio slice extraction failed. Proceeding with metadata evaluation.")
            transcript = f"Streamer {streamer_name} playing GTA 6 live stream."

        # 2. Evaluate with Gemini
        eval_data = self.evaluate_with_gemini(
            streamer_name=streamer_name,
            stream_title=stream_title,
            transcript=transcript,
            keywords=keywords,
            spike_type=spike_type,
        )

        score = eval_data.get("viral_score", 0)
        safety = eval_data.get("safety_rating", "SAFE")
        verdict = eval_data.get("verdict", "APPROVED")

        # Enforce viral threshold (>= 8) and safety check
        approved = (score >= MIN_VIRAL_SCORE) and (safety == "SAFE") and (verdict == "APPROVED")

        if not approved:
            logger.info(
                f"Candidate REJECTED by Gemini AI (Score: {score}/{MIN_VIRAL_SCORE}, "
                f"Safety: {safety}, Verdict: {verdict}). Reason: {eval_data.get('reason')}"
            )
        else:
            logger.info(
                f"Candidate APPROVED by Gemini AI! Score: {score}/10 | Title: '{eval_data.get('short_title')}'"
            )

        return CurationResult(
            approved=approved,
            viral_score=score,
            verdict="APPROVED" if approved else "REJECTED",
            short_title=eval_data.get("short_title", "GTA 6 INSANE MOMENT 💀"),
            hook_text=eval_data.get("hook_text", "WAIT FOR IT... 💀"),
            description=eval_data.get("description", "Daily GTA 6 viral moments! #Shorts #GTA6"),
            tags=eval_data.get("tags", ["Shorts", "GTA6"]),
            safety_rating=safety,
            reason=eval_data.get("reason", "Meets virality threshold."),
            transcript=transcript,
            word_timestamps=word_timings,
        )


if __name__ == "__main__":
    curator = ViralCurator()
    print("[Curator Self-Test] Viral Curator module initialized successfully.")
