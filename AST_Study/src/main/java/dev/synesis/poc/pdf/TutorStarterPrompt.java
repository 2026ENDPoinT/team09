package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.util.function.Consumer;
import javax.swing.JButton;

/** Display text is user-visible; only a fixed task ID crosses the worker boundary. */
enum TutorStarterPrompt {
    BACKGROUND_KNOWLEDGE("background_knowledge", "이해에 필요한 배경지식 설명해줘."),
    KEY_CONCEPTS("key_concepts", "핵심 개념들만 모아줘."),
    EXAM_PREDICTION("exam_prediction", "시험 출제 예상해줘.");

    private final String id, label;
    TutorStarterPrompt(String id, String label) {this.id=id;this.label=label;}
    String label() {return label;}
    void addTo(JsonObject request) {
        if (!request.has("question") || !label.equals(request.get("question").getAsString()))
            throw new IllegalArgumentException("AI멘토 시작 질문이 버튼과 일치하지 않아요.");
        request.addProperty("starterId",id);
    }
    JButton button(Consumer<TutorStarterPrompt> onSelect) {
        JButton button=new JButton(label);
        button.addActionListener(event->onSelect.accept(this));
        return button;
    }
}
