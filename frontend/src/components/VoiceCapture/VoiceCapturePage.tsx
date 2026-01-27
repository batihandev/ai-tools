import { useState } from "react";
import { CaptureCard } from "./CaptureCard";
import { HistoryCard } from "./HistoryCard";
import { LatestTranscriptCard } from "./LatestTranscriptCard";
import { TeacherChatCard } from "./TeacherChatCard";
import { ModeSettingsModal } from "./ModeSettingsModal";
import { useTeacherChat } from "./useTeacherChat";
import { useVoiceCapture } from "./useVoiceCapture";

export function VoiceCapturePage() {
  const [modeModalOpen, setModeModalOpen] = useState(false);
  const teacher = useTeacherChat();

  const vc = useVoiceCapture({
    onNewTranscript: (t) => {
      // raw only in the chat, per your request
      teacher.onTranscript(t.raw_text);
    },
  });

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <div className="mb-5">
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
          Voice
        </h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Speak normally. When you stop talking, the utterance is finalized and
          transcribed. The teacher responds in batches; if you keep talking
          while it’s responding, your transcripts are queued and sent together
          next.
        </p>
      </div>

      <div className="grid gap-4">
        <TeacherChatCard
          messages={teacher.messages}
          aiTyping={teacher.aiTyping}
          currentMode={teacher.mode}
          onModeSettingsClick={() => setModeModalOpen(true)}
          onClear={teacher.clear}
        />

        <LatestTranscriptCard
          key={vc.latest?.id}
          latest={vc.latest}
          audioBlob={vc.lastAudioBlob}
          onRetry={(text) => teacher.onTranscript(text)}
          pauseListening={vc.pauseListening}
          resumeListening={vc.resumeListening}
        />

        <CaptureCard
          isListening={vc.isListening}
          status={vc.status}
          statusPillClass={vc.statusPillClass}
          showAdvanced={vc.showAdvanced}
          setShowAdvanced={vc.setShowAdvanced}
          silenceMs={vc.silenceMs}
          setSilenceMs={vc.setSilenceMs}
          threshold={vc.threshold}
          setThreshold={vc.setThreshold}
          rmsTooltip={vc.rmsTooltip}
          startListening={vc.startListening}
          stopAll={vc.stopAll}
          refreshHistory={vc.refreshHistory}
          resetDefaults={vc.resetDefaults}
        />

        <HistoryCard history={vc.history} />
      </div>

      <ModeSettingsModal
        isOpen={modeModalOpen}
        currentMode={teacher.mode}
        onModeChange={(newMode) => teacher.setMode(newMode)}
        onClose={() => setModeModalOpen(false)}
      />
    </div>
  );
}
