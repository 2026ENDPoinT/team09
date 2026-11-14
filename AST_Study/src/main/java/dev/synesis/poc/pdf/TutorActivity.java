package dev.synesis.poc.pdf;

/** EDT-only presentation state for PDF retrieval and answer generation. */
final class TutorActivity {
    enum Stage {
        PDF("멘토가 PDF를 검색 중이에요."),
        THINKING("멘토가 깊게 생각 중이에요.");
        final String text;
        Stage(String text) { this.text=text; }
    }
    private final Runnable changed;
    private String marker;
    private Stage stage=Stage.PDF;

    TutorActivity(Runnable changed) {
        this.changed=changed;
    }
    void start(String marker) {
        this.marker=marker;stage=Stage.PDF;changed.run();
    }
    void pdfSearchDone(String marker) {
        answerStarted(marker);
    }
    void answerStarted(String marker) {
        if(this.marker==null || !this.marker.equals(marker) || stage==Stage.THINKING)return;
        stage=Stage.THINKING;changed.run();
    }
    void clear() { marker=null; }
    String text() {return stage.text;}
}
