import { useCallback, useEffect, useRef, useState } from "react";
import { postChat, postChatAudio, postSynthesize, postTranscribe } from "../api/client";
import type { ChatMessage, ChatResponse, Locale, VoicePhase } from "../types/chat";
import { localeForTts, newId, plainTextForTts } from "../utils/text";

/** Ms of quiet after real speech before we send the clip */
const SILENCE_MS = 1800;
/** Min clip length once speech was detected */
const MIN_SPEECH_MS = 600;
const MAX_RECORD_MS = 28000;
/** Consecutive frames above start threshold (~50ms each at 60fps) */
const START_SPEECH_FRAMES = 5;
/** Consecutive frames below silence threshold to treat as noise (don't start) */
const CALIBRATION_MS = 700;
/** Ignore mic after agent speaks (prevents speaker echo re-triggering VAD) */
const POST_PLAYBACK_COOLDOWN_MS = 1600;
/** Max capture length once real speech was detected */
const MAX_UTTERANCE_MS = 14000;
/** Discard accidental clip if only noise, no speech */
const NO_SPEECH_ABORT_MS = 3200;

type TurnHandler = (user: string, data: ChatResponse) => void;
type UserUtteranceHandler = (user: string) => void;

interface VadThresholds {
  start: number;
  continue: number;
  silence: number;
}

function pickMime(): string {
  if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) return "audio/webm;codecs=opus";
  if (MediaRecorder.isTypeSupported("audio/webm")) return "audio/webm";
  return "";
}

function measureRms(analyser: AnalyserNode): number {
  const data = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(data);
  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    const v = (data[i] - 128) / 128;
    sum += v * v;
  }
  return Math.sqrt(sum / data.length);
}

/** Build thresholds from ambient noise floor (75th percentile). */
function thresholdsFromNoiseFloor(floor: number): VadThresholds {
  const base = Math.max(floor, 0.004);
  return {
    start: Math.max(0.022, base * 2.6 + 0.01),
    continue: Math.max(0.016, base * 1.65 + 0.006),
    silence: Math.max(0.012, base * 1.2 + 0.004),
  };
}

function defaultThresholds(): VadThresholds {
  return { start: 0.032, continue: 0.022, silence: 0.016 };
}

export function useVoiceAssistant(
  threadId: string,
  hintLocale: Locale,
  enabled: boolean,
  onTurn: TurnHandler,
  onUserUtterance?: UserUtteranceHandler,
  nativeAudioLlm = false,
) {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [status, setStatus] = useState("Starting…");
  const [hint, setHint] = useState("Allow microphone access");
  const [error, setError] = useState<string | null>(null);
  const [interim, setInterim] = useState("");

  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const rafRef = useRef<number>(0);
  const loopActiveRef = useRef(false);
  const processingRef = useRef(false);
  const speechStartedRef = useRef(false);
  const silenceSinceRef = useRef<number | null>(null);
  const recordStartRef = useRef(0);
  const loudFramesRef = useRef(0);
  const vadRef = useRef<VadThresholds>(defaultThresholds());
  const calibratingRef = useRef(false);
  const localeRef = useRef(hintLocale);
  const threadRef = useRef(threadId);
  const playingRef = useRef<HTMLAudioElement | null>(null);
  const listenPausedUntilRef = useRef(0);
  const phaseRef = useRef<VoicePhase>("idle");

  localeRef.current = hintLocale;
  threadRef.current = threadId;

  const setPhaseSafe = (p: VoicePhase) => {
    phaseRef.current = p;
    setPhase(p);
  };

  const isListenPaused = () => Date.now() < listenPausedUntilRef.current;

  const setMicEnabled = (on: boolean) => {
    streamRef.current?.getAudioTracks().forEach((t) => {
      t.enabled = on;
    });
  };

  /** Stop capture and mute mic while agent thinks / speaks (blocks TTS echo). */
  const haltListening = useCallback(() => {
    listenPausedUntilRef.current = Date.now() + POST_PLAYBACK_COOLDOWN_MS;
    loudFramesRef.current = 0;
    speechStartedRef.current = false;
    silenceSinceRef.current = null;
    setInterim("");
    const rec = recorderRef.current;
    if (rec && rec.state === "recording") {
      recorderRef.current = null;
      chunksRef.current = [];
      try {
        rec.stop();
      } catch {
        /* already stopped */
      }
    }
    setMicEnabled(false);
  }, []);

  const monitorRef = useRef<() => void>(() => {});

  const resumeListening = useCallback(() => {
    listenPausedUntilRef.current = Date.now() + POST_PLAYBACK_COOLDOWN_MS;
    window.setTimeout(() => {
      if (processingRef.current) return;
      loopActiveRef.current = true;
      listenPausedUntilRef.current = 0;
      setMicEnabled(true);
      loudFramesRef.current = 0;
      cancelAnimationFrame(rafRef.current);
      monitorRef.current();
    }, POST_PLAYBACK_COOLDOWN_MS);
  }, []);

  const stopRecorder = useCallback((): Promise<Blob> => {
    return new Promise((resolve) => {
      const rec = recorderRef.current;
      if (!rec || rec.state === "inactive") {
        resolve(new Blob(chunksRef.current, { type: "audio/webm" }));
        return;
      }
      rec.onstop = () => resolve(new Blob(chunksRef.current, { type: "audio/webm" }));
      rec.stop();
    });
  }, []);

  const playBlob = useCallback(async (blob: Blob) => {
    if (!blob.size) throw new Error("Empty audio response");
    if (playingRef.current) {
      playingRef.current.pause();
      playingRef.current = null;
    }
    const url = URL.createObjectURL(blob);
    await new Promise<void>((resolve, reject) => {
      const audio = new Audio(url);
      audio.volume = 1;
      playingRef.current = audio;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        playingRef.current = null;
        resolve();
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error("Audio playback failed"));
      };
      void audio.play().catch(reject);
    });
  }, []);

  const playModelReply = useCallback(
    async (chat: ChatResponse, userLabel: string) => {
      const reply = chat.response || "";
      const spoken = plainTextForTts(reply);
      const ttsLocale = localeForTts(reply, chat.reply_locale, localeRef.current);
      localeRef.current = ttsLocale;

      onTurn(userLabel, chat);

      setPhaseSafe("speaking");
      setStatus(ttsLocale === "ar" ? "يتحدث…" : "Speaking…");
      setHint("");
      try {
        const audioBlob = await postSynthesize(spoken, ttsLocale);
        await playBlob(audioBlob);
      } catch (speakErr) {
        const msg = speakErr instanceof Error ? speakErr.message : String(speakErr);
        setError(`Could not play voice (${ttsLocale}): ${msg}`);
      }

      setPhaseSafe("listening");
      setStatus("Listening…");
      setHint(
        chat.pending_confirmation
          ? "Confirm or cancel — speak or use buttons"
          : "Speak clearly — pause ~2s when finished",
      );
    },
    [onTurn, playBlob],
  );

  const voiceTurn = useCallback(
    async (fetchChat: () => Promise<ChatResponse>, userLabel: string) => {
      haltListening();
      processingRef.current = true;
      setInterim("");
      setPhaseSafe("thinking");
      setStatus("Thinking…");
      setHint(userLabel.length > 56 ? `${userLabel.slice(0, 56)}…` : userLabel);
      setError(null);
      onUserUtterance?.(userLabel);

      try {
        const chat = await fetchChat();
        await playModelReply(chat, userLabel);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        setPhaseSafe("listening");
        setStatus("Listening…");
        setHint("Try again");
      } finally {
        processingRef.current = false;
        resumeListening();
      }
    },
    [haltListening, onUserUtterance, playModelReply, resumeListening],
  );

  const runTurn = useCallback(
    async (userText: string) => {
      await voiceTurn(() => postChat(userText, threadRef.current), userText);
    },
    [voiceTurn],
  );

  const processRecording = useCallback(async () => {
    if (processingRef.current) return;
    processingRef.current = true;
    setMicEnabled(false);
    const blob = await stopRecorder();
    recorderRef.current = null;
    chunksRef.current = [];
    speechStartedRef.current = false;
    silenceSinceRef.current = null;
    loudFramesRef.current = 0;
    listenPausedUntilRef.current = Date.now() + POST_PLAYBACK_COOLDOWN_MS;

    const minBytes = 400;
    if (blob.size < minBytes) {
      processingRef.current = false;
      setPhaseSafe("listening");
      setStatus("Listening…");
      setHint("Didn't catch speech — speak a bit louder and pause when done");
      resumeListening();
      return;
    }

    setPhaseSafe("thinking");
    setStatus(nativeAudioLlm ? "Sending audio…" : "Understanding…");
    setHint("");
    try {
      if (nativeAudioLlm) {
        await voiceTurn(async () => {
          const chat = await postChatAudio(blob, threadRef.current, localeRef.current);
          localeRef.current = chat.reply_locale || localeRef.current;
          return chat;
        }, "(voice)");
      } else {
        const tr = await postTranscribe(blob, localeRef.current);
        localeRef.current = tr.locale || localeRef.current;
        await voiceTurn(() => postChat(tr.text, threadRef.current), tr.text);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      setPhaseSafe("listening");
      setStatus("Listening…");
      setHint("Try again");
      processingRef.current = false;
      resumeListening();
    }
  }, [nativeAudioLlm, resumeListening, stopRecorder, voiceTurn]);

  const beginRecording = useCallback((now: number) => {
    if (!streamRef.current) return;
    setMicEnabled(true);
    chunksRef.current = [];
    speechStartedRef.current = false;
    silenceSinceRef.current = null;
    recordStartRef.current = now;
    loudFramesRef.current = 0;
    const mime = pickMime();
    const stream = streamRef.current;
    const recorder = mime
      ? new MediaRecorder(stream, { mimeType: mime })
      : new MediaRecorder(stream);
    recorder.ondataavailable = (e) => {
      if (e.data.size) chunksRef.current.push(e.data);
    };
    recorder.start(200);
    recorderRef.current = recorder;
    setPhaseSafe("listening");
    setStatus("Listening…");
    setInterim("Hearing you…");
  }, []);

  const abortRecording = useCallback(() => {
    const rec = recorderRef.current;
    recorderRef.current = null;
    chunksRef.current = [];
    speechStartedRef.current = false;
    silenceSinceRef.current = null;
    loudFramesRef.current = 0;
    setInterim("");
    if (rec && rec.state === "recording") {
      try {
        rec.stop();
      } catch {
        /* noop */
      }
    }
  }, []);

  const monitor = useCallback(() => {
    const analyser = analyserRef.current;

    const canListen =
      !!analyser &&
      loopActiveRef.current &&
      !processingRef.current &&
      !calibratingRef.current &&
      !isListenPaused();

    if (canListen) {
    const { start, continue: cont, silence } = vadRef.current;
    const level = measureRms(analyser);
    const now = Date.now();
    const rec = recorderRef.current;

    if (rec && rec.state === "recording") {
      const isSpeech = level > cont;

      if (isSpeech) {
        speechStartedRef.current = true;
        silenceSinceRef.current = null;
        setInterim("…");
      } else if (speechStartedRef.current) {
        if (silenceSinceRef.current === null) silenceSinceRef.current = now;
        else if (
          now - silenceSinceRef.current >= SILENCE_MS &&
          now - recordStartRef.current >= MIN_SPEECH_MS
        ) {
          void processRecording();
        }
      } else if (now - recordStartRef.current > NO_SPEECH_ABORT_MS) {
        abortRecording();
        setPhaseSafe("listening");
        setStatus("Listening…");
        setHint("Speak clearly — pause ~2s when finished");
      }

      if (
        speechStartedRef.current &&
        now - recordStartRef.current > MAX_UTTERANCE_MS
      ) {
        void processRecording();
      } else if (now - recordStartRef.current > MAX_RECORD_MS) {
        void processRecording();
      }
    } else {
      // Not recording: require sustained loud frames before starting (ignores brief noise)
      if (level > start && !isListenPaused()) {
        loudFramesRef.current += 1;
        if (loudFramesRef.current >= START_SPEECH_FRAMES) {
          beginRecording(now);
        }
      } else if (level < silence) {
        loudFramesRef.current = 0;
      } else {
        // Between silence and start — decay counter slowly
        loudFramesRef.current = Math.max(0, loudFramesRef.current - 1);
      }
    }
    }

    rafRef.current = requestAnimationFrame(monitor);
  }, [abortRecording, beginRecording, processRecording]);

  monitorRef.current = () => {
    rafRef.current = requestAnimationFrame(monitor);
  };

  const calibrateNoise = useCallback(async (analyser: AnalyserNode) => {
    calibratingRef.current = true;
    setStatus("Calibrating…");
    setHint("Stay quiet for a moment (background noise)");
    const samples: number[] = [];
    const t0 = Date.now();
    await new Promise<void>((resolve) => {
      const tick = () => {
        samples.push(measureRms(analyser));
        if (Date.now() - t0 >= CALIBRATION_MS) resolve();
        else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    samples.sort((a, b) => a - b);
    const idx = Math.min(samples.length - 1, Math.floor(samples.length * 0.75));
    const floor = samples[idx] ?? 0.01;
    vadRef.current = thresholdsFromNoiseFloor(floor);
    calibratingRef.current = false;
    listenPausedUntilRef.current = 0;
    setMicEnabled(true);
    setPhaseSafe("listening");
    setStatus("Listening…");
    setHint("Speak clearly — pause ~2s when finished");
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setPhaseSafe("idle");
    setStatus("Requesting microphone…");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;
      const ctx = new AudioContext();
      await ctx.resume();
      audioCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.85;
      src.connect(analyser);
      analyserRef.current = analyser;
      loopActiveRef.current = true;
      await calibrateNoise(analyser);
      rafRef.current = requestAnimationFrame(monitor);
    } catch {
      setPhaseSafe("idle");
      setStatus("Microphone blocked");
      setHint("Enable mic in browser settings and refresh");
      setError("Microphone permission denied.");
    }
  }, [calibrateNoise, monitor]);

  const stop = useCallback(() => {
    loopActiveRef.current = false;
    calibratingRef.current = false;
    cancelAnimationFrame(rafRef.current);
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    recorderRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    void audioCtxRef.current?.close();
    audioCtxRef.current = null;
    if (playingRef.current) playingRef.current.pause();
    loudFramesRef.current = 0;
    listenPausedUntilRef.current = 0;
    setPhaseSafe("idle");
    setInterim("");
  }, []);

  const sendConfirm = useCallback(
    async (msg: string) => {
      haltListening();
      processingRef.current = true;
      loopActiveRef.current = false;
      setPhaseSafe("thinking");
      setStatus("Saving…");
      setError(null);
      try {
        await runTurn(msg);
      } finally {
        processingRef.current = false;
        loopActiveRef.current = true;
        resumeListening();
      }
    },
    [haltListening, resumeListening, runTurn],
  );

  useEffect(() => {
    if (enabled) void start();
    else stop();
    return () => stop();
  }, [enabled, start, stop]);

  return {
    phase,
    status,
    hint,
    error,
    interim,
    sendConfirm,
  };
}

export function appendTurnMessages(
  prev: ChatMessage[],
  user: string,
  assistant: string,
): ChatMessage[] {
  return [
    ...prev,
    { id: newId(), role: "user", content: user },
    { id: newId(), role: "assistant", content: assistant },
  ];
}
