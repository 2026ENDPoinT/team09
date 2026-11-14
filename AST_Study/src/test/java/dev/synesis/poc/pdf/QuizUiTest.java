package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.awt.Component;
import java.awt.Container;
import java.awt.Dimension;
import java.awt.FlowLayout;
import java.awt.Graphics2D;
import java.awt.Insets;
import java.awt.image.BufferedImage;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;
import javax.imageio.ImageIO;
import javax.swing.AbstractButton;
import javax.swing.JButton;
import javax.swing.JComponent;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.SwingUtilities;

/** Local contracts and offscreen paints only. No frame, actual app, model, network, or saved PDF data. */
public final class QuizUiTest {
    private static final String DOC="quiz-ui-fixture";
    private static final String USER_ANSWER="내 답변은 모범답안과 다른 표현이에요.\n조건도 함께 설명해요.";
    private static Path output;

    public static void main(String[] args) throws Exception {
        output=Path.of(args.length==0?"build/quiz-ui-scaffold":args[0]);
        Files.createDirectories(output);
        try {
            SwingUtilities.invokeAndWait(()->{
                try {
                    if(List.of(args).contains("--tutor-contract-only")){comparisonAndTutor();return;}
                    settingsAndThemes();
                    staleSettingsActions();
                    fixedHeaderAndPlainBackground();
                    generationLifecycle();
                    liveGenerationPlaying();
                    workbookProgressAndStaleOpen();
                    comparisonAndTutor();
                    objectiveCards();
                    staleDocumentAndScope();
                    // The optional visual suite also covers the separate generation/settings screen.
                    if(!List.of(args).contains("--behavior-only"))render();
                } catch(Exception error) {throw new RuntimeException(error);}
            });
        } catch(Throwable failure) {
            failure.printStackTrace();System.exit(1);
        }
        System.out.println(List.of(args).contains("--tutor-contract-only")
            ? "QuizUiTest passed: N제 tutor button sends the current answer, criteria, explanation and grading request; blank answers remain ungraded. No paid calls."
            : "QuizUiTest passed: workbook creation and list selection, saved answer/reveal state, stale-open guards, count and readiness guards, cost reports, shared settings, comparison, tutor snapshots, and headless renders. No paid calls.");
        System.exit(0);
    }

    private static QuizPanel panel() {
        QuizPanel panel=new QuizPanel();
        panel.reset(12,DOC);panel.setReady(true);
        return panel;
    }

    private static void staleSettingsActions() {
        QuizPanel panel=panel();panel.settings.doClick();
        JButton oldApply=button(panel.detailsHost,"설정 적용"),oldClose=button(panel.detailsHost,"닫기");
        panel.settings.doClick();panel.settings.doClick();
        QuizPanel.Settings current=panel.detailForm;current.level.setSelectedItem("상");
        // A click queued before collapse may arrive after the next form opens.
        for(JButton previous:List.of(oldApply,oldClose))
            for(var listener:previous.getActionListeners())
                listener.actionPerformed(new java.awt.event.ActionEvent(previous,java.awt.event.ActionEvent.ACTION_PERFORMED,"queued"));
        require(panel.detailForm==current&&panel.detailsHost.isExpanded(),"a stale settings action closed or replaced the current form");
        equal(panel.configuration().difficulty(),"중","a stale settings action applied an abandoned draft");
        button(panel.detailsHost,"설정 적용").doClick();
        panel.totalCount.setValue(23);panel.themeButtons.get(QuizPanel.Theme.PRACTICE).doClick();
        String cover=panel.bookPreview.getAccessibleContext().getAccessibleDescription();
        require(cover.contains("N제")&&cover.contains("난이도 상")&&cover.contains("23문제"),"cover lost the selected workbook settings");
    }

    private static void fixedHeaderAndPlainBackground() throws Exception {
        QuizPanel panel=panel();paint(panel,760,850,"plain-background.png");
        java.awt.BorderLayout layout=(java.awt.BorderLayout)panel.getLayout();
        Component header=layout.getLayoutComponent(java.awt.BorderLayout.NORTH);
        require(header instanceof Container&&containsLabel((Container)header,"N제로 학습"),"workspace-style quiz heading is missing");
        require(header.getHeight()==42,"quiz heading no longer matches the workspace headings");
        var scrollField=QuizPanel.class.getDeclaredField("scroll");scrollField.setAccessible(true);
        javax.swing.JScrollPane pane=(javax.swing.JScrollPane)scrollField.get(panel);
        require(pane.getViewport().getScrollMode()==javax.swing.JViewport.BLIT_SCROLL_MODE,"quiz scrolling must reuse unchanged pixels");
        BufferedImage image=ImageIO.read(output.resolve("plain-background.png").toFile());
        for(int y:List.of(34,68,102,170,340))
            require((image.getRGB(5,header.getHeight()+y)&0xffffff)==0xffffff,"graph-paper background escaped the book preview");
        int top=header.getY();pane.getViewport().setViewPosition(new java.awt.Point(0,150));
        require(header.getY()==top,"quiz header scrolled with the content");
    }

    private static boolean containsLabel(Container parent,String text) {
        for(Component child:parent.getComponents()) {
            if(child instanceof JLabel label&&text.equals(label.getText()))return true;
            if(child instanceof Container nested&&containsLabel(nested,text))return true;
        }
        return false;
    }

    private static void settingsAndThemes() throws Exception {
        QuizPanel panel=panel();
        equal(panel.configuration().difficulty(),"중","default difficulty");
        equal(panel.configuration().types(),EnumSet.allOf(QuizQuestion.Type.class),"all default formats");
        require(!panel.generate.isEnabled(),"generation must require concept readiness and a handler");
        equal(QuizPanel.LEVELS,List.of("중","중상","상","최상"),"difficulty choices");
        panel.settings.doClick();
        QuizPanel.Settings form=panel.detailForm;
        require(form!=null&&panel.detailsHost.isVisible(),"settings did not open");
        form.level.setSelectedItem("중상");
        form.formats.forEach((type,box)->box.setSelected(type.selfComparison()));
        form.from.setValue(2);form.to.setValue(8);form.extra.setText("조건 비교");
        button(panel.detailsHost,"설정 적용").doClick();
        QuizPanel.Configuration chosen=panel.configuration();
        equal(chosen.difficulty(),"중상","saved difficulty");
        equal(chosen.types(),Set.of(QuizQuestion.Type.SHORT_ANSWER,QuizQuestion.Type.ESSAY),"saved formats");
        equal(chosen.start(),2,"saved range start");equal(chosen.end(),8,"saved range end");
        for(QuizPanel.Theme theme:QuizPanel.Theme.values()) {
            panel.themeButtons.get(theme).doClick();
            equal(panel.selectedTheme(),theme,"selected theme");
            require(panel.themeButtons.values().stream().filter(AbstractButton::isSelected).count()==1,"multiple themes selected");
            equal(panel.configuration(),chosen,"theme changed common settings");
        }
        panel.showPreview();
        require(panel.cards.size()==1&&panel.studyView.questionCount()==2,"preview ignored selected formats");
        require(panel.cards.stream().allMatch(c->c.question.selfComparison()),"unselected objective format in preview");
        panel.settings.doClick();
        panel.detailForm.level.setSelectedItem("최상");
        panel.detailForm.formats.values().forEach(box->box.setSelected(false));
        button(panel.detailsHost,"설정 적용").doClick();
        require(panel.detailsHost.isVisible(),"zero formats were accepted");
        equal(panel.configuration(),chosen,"invalid draft changed saved settings");
        button(panel.detailsHost,"닫기").doClick();
        equal(panel.configuration(),chosen,"cancel changed saved settings");
        panel.settings.doClick();
        equal(panel.detailForm.level.getSelectedItem(),"중상","cancelled difficulty leaked");
        panel.detailForm.from.setValue(9);panel.detailForm.to.setValue(3);
        button(panel.detailsHost,"설정 적용").doClick();
        equal(panel.configuration(),chosen,"invalid range changed saved settings");
        button(panel.detailsHost,"닫기").doClick();
        try {chosen.types().clear();throw new AssertionError("settings set is mutable");}
        catch(UnsupportedOperationException expected) {}
        panel.reset(0,"");require(!panel.settings.isEnabled()&&!panel.preview.isEnabled(),"settings enabled without a PDF");
    }

    private static void generationLifecycle() {
        QuizPanel panel=panel();
        List<QuizPanel.GenerationRequest> sent=new ArrayList<>();
        panel.setGenerationRequestHandler(sent::add);
        equal(panel.generate.getText(),"문제 생성하기","workbook generation action");
        equal(panel.totalCount.getValue(),10,"default question count");
        require(!panel.generate.isEnabled(),"generation enabled before concepts");
        panel.generate.doClick();require(sent.isEmpty(),"disabled generation invoked handler");
        panel.setGenerationReady(true);panel.totalCount.setValue(17);
        panel.themeButtons.get(QuizPanel.Theme.UNDERSTANDING).doClick();
        panel.settings.doClick();panel.detailForm.level.setSelectedItem("상");
        panel.detailForm.from.setValue(2);panel.detailForm.to.setValue(9);
        panel.detailForm.extra.setText("인과관계 중심");
        panel.detailForm.formats.forEach((type,box)->box.setSelected(type==QuizQuestion.Type.ESSAY));
        require(sent.isEmpty(),"settings generated without a click");panel.generate.doClick();
        require(sent.size()==1,"generation click not dispatched once");
        QuizPanel.GenerationRequest snapshot=sent.get(0);
        equal(snapshot.totalCount(),17,"question count missing");
        equal(snapshot.theme(),QuizPanel.Theme.UNDERSTANDING,"theme missing");
        equal(snapshot.configuration().difficulty(),"상","draft settings not applied");
        equal(snapshot.configuration().start(),2,"page range start missing");
        equal(snapshot.configuration().end(),9,"page range end missing");
        equal(snapshot.configuration().types(),Set.of(QuizQuestion.Type.ESSAY),"formats missing");
        equal(snapshot.configuration().instructions(),"인과관계 중심","instructions missing");
        require(!panel.generate.isEnabled()&&!panel.settings.isEnabled()&&!panel.preview.isEnabled()&&!panel.totalCount.isEnabled(),"busy controls enabled");
        require(panel.themeButtons.values().stream().noneMatch(AbstractButton::isEnabled),"busy themes enabled");
        panel.generate.doClick();require(sent.size()==1,"busy generation dispatched twice");
        panel.setGenerating(true,"개념 묶음 1/2 출제 중");
        require(panel.generationStatus.getText().contains("문제를 생성중이에요."),"generation notice lost");
        panel.setGenerating(true,"문항 출제 중 · 완료 1/2묶음 · 동시 1개");
        require(panel.generate.getText().contains("48%"),"batch progress missing from create button");
        panel.setGenerating(true,"문항의 정답·조건·난이도와 문장을 함께 검토하고 있어요.");
        require(panel.generate.getText().contains("90%"),"review must remain below completion");
        panel.setGenerating(true,"문항 출제 중 · 완료 2/2묶음 · 동시 0개");
        require(panel.generate.getText().contains("90%"),"late events must not reverse progress");
        panel.showGenerationResult(List.of(question(QuizQuestion.Type.ESSAY)),65.2,.012,17,"일부 자료에서 근거를 확인하지 못했어요.");
        require(panel.generate.isEnabled()&&panel.totalCount.isEnabled(),"generation controls not restored");
        require(panel.generate.getText().contains("100%"),"saved workbook must complete progress");
        try {
            var field=QuizPanel.class.getDeclaredField("completionReset");field.setAccessible(true);
            javax.swing.Timer timer=(javax.swing.Timer)field.get(panel);
            require(timer.isRunning()&&!timer.isRepeats()&&timer.getInitialDelay()==3000,"completion reset must run once after three seconds");
            for(var listener:timer.getActionListeners())listener.actionPerformed(new java.awt.event.ActionEvent(timer,0,"test"));
            equal(panel.generate.getText(),"문제 생성하기","completed button did not return to generation action");
            require(panel.generate.isEnabled(),"reset completion disabled next generation");
        } catch(ReflectiveOperationException failure){throw new AssertionError(failure);}

        require(panel.cards.isEmpty()&&panel.currentWorkbookId().isEmpty(),"generation automatically opened questions");
        require(panel.workbooks().size()==1&&panel.workbookButtons.size()==1,"generated workbook missing from list");
        QuizWorkbook first=panel.workbooks().get(0);
        equal(first.theme(),QuizPanel.Theme.UNDERSTANDING,"workbook lost its generation theme");
        String report=panel.generationReport.getText();
        require(report.contains("생성 1 / 17문제")&&report.contains("총 시간 1분 5초"),"count or time missing");
        require(report.contains("총 사용 7.30 크레딧")&&report.contains("문제당 7.30 크레딧"),"shared credit conversion omitted or divided by requested count");
        require(report.contains("배분·생성 비용 포함")&&!report.contains("$")&&!report.contains("원 환산"),"cost scope missing or old currency display retained");
        JButton firstOpenButton=panel.workbookButtons.get(first.id());firstOpenButton.doClick();
        require(panel.cards.size()==1&&panel.currentWorkbookId().equals(first.id()),"workbook click did not open questions");
        panel.cards.get(0).answerInput.setText(USER_ANSWER);panel.cards.get(0).checkButton.doClick();
        panel.workbookBack.doClick();
        require(panel.workbookButtons.get(first.id())==firstOpenButton,"returning to an unchanged list rebuilt saved workbook controls");
        require(panel.cards.isEmpty()&&panel.workbooks().size()==1,"back did not restore the workbook list");
        panel.themeButtons.get(QuizPanel.Theme.RECALL).doClick();
        equal(first.theme(),QuizPanel.Theme.UNDERSTANDING,"new generation theme changed an existing workbook");
        panel.showPreview();require(panel.cards.size()==1&&panel.cards.get(0).question.preview(),"preview ignored selected type");
        panel.preview.doClick();require(panel.cards.isEmpty()&&panel.workbooks().size()==1,"preview became a workbook or opened saved questions");
        panel.setGenerating(true,"다시 출제 중");panel.showGenerationFailure("연결이 중단됐어요.");
        require(panel.workbooks().size()==1&&panel.generationReport.getText().equals(report),"failure erased workbook or usage");
        require(panel.generationStatus.getText().contains("이전에 만든 문제집은 유지"),"failure preservation unclear");
        panel.showGenerationResult(List.of(),2,.004,17,"");
        require(!panel.generationReport.getText().contains("문제당"),"zero questions showed a unit price");
        require(panel.workbooks().size()==1&&panel.cards.isEmpty(),"zero-question result erased the workbook list");
        require(panel.generationReport.getText().contains("생성 0 / 17문제")&&panel.generationReport.getText().contains("총 사용 2.43 크레딧"),"zero-question attempt lost its own usage");
        panel.workbookButtons.get(first.id()).doClick();
        equal(panel.cards.get(0).userAnswer(),USER_ANSWER,"returning to workbook lost the answer");
        require(panel.cards.get(0).answerRevealed(),"returning to workbook lost answer reveal state");
        panel.workbookBack.doClick();
        panel.showGenerationResult(List.of(question(QuizQuestion.Type.ESSAY)),2,null,1,"");
        require(panel.workbooks().size()==2&&panel.cards.isEmpty(),"second workbook replaced the first or auto-opened");
        require(panel.generationReport.getText().contains("사용 크레딧 확인 대기")&&!panel.generationReport.getText().contains("0.00 크레딧"),"unknown usage treated as free");
        panel.showGenerationResult(List.of(question(QuizQuestion.Type.ESSAY)),2,0d,1,"");
        require(panel.workbooks().size()==3&&panel.generationReport.getText().contains("총 사용 0.00 크레딧"),"known zero usage not shown");
        panel.setGenerationReady(false);panel.setReady(false);
        require(panel.workbookButtons.values().stream().allMatch(AbstractButton::isEnabled),"saved workbooks require generation readiness");
        panel.reset(12,"new-document");panel.setReady(true);
        require(!panel.generate.isEnabled()&&!panel.generationReport.isVisible()&&panel.workbooks().isEmpty(),"document reset retained a workbook or old costs");
        equal(panel.totalCount.getValue(),10,"document reset retained old count");
    }

    private static void workbookProgressAndStaleOpen() {
        QuizPanel panel=panel();
        QuizWorkbook one=workbook("one",QuizPanel.Theme.PRACTICE,question(QuizQuestion.Type.ESSAY));
        QuizWorkbook two=workbook("two",QuizPanel.Theme.RECALL,question(QuizQuestion.Type.OX));
        panel.setWorkbooks(List.of(one,two));
        List<QuizWorkbook> requested=new ArrayList<>();panel.setWorkbookOpenHandler(requested::add);
        AtomicReference<java.util.Map<String,QuizWorkbook.Answer>> saved=new AtomicReference<>();
        List<String> progressBooks=new ArrayList<>();
        panel.setWorkbookProgressHandler((book,answers)->{saved.set(answers);progressBooks.add(book.id());});
        panel.workbookButtons.get(one.id()).doClick();panel.workbookButtons.get(two.id()).doClick();
        equal(requested.size(),2,"workbook selection did not route to the loader");
        panel.openWorkbook(one,java.util.Map.of());require(panel.cards.isEmpty(),"late first selection reopened the wrong workbook");
        panel.openWorkbook(two,java.util.Map.of(two.questions().get(0).id(),new QuizWorkbook.Answer("X",true)));
        equal(panel.currentWorkbookId(),two.id(),"second selection did not open");
        QuizQuestionCard old=panel.cards.get(0);
        equal(old.userAnswer(),"X","saved objective selection not restored");require(old.answerRevealed(),"saved objective reveal not restored");
        old.choiceButtons.get("O").doClick();require(old.answerRevealed()&&old.userAnswer().equals("X"),"graded answer must stay fixed until a new attempt");
        old.bookmarkButton.doClick();
        require(saved.get()!=null&&saved.get().get(old.question.id()).revealed(),"bookmark edit lost saved grading");
        panel.workbookBack.doClick();
        panel.openWorkbook(two,java.util.Map.of());require(panel.cards.isEmpty(),"late load reopened a workbook after returning to list");
        panel.workbookButtons.get(one.id()).doClick();panel.openWorkbook(one,java.util.Map.of());
        panel.cards.get(0).answerInput.setText(USER_ANSWER);panel.cards.get(0).checkButton.doClick();
        equal(saved.get().get(one.questions().get(0).id()).answer(),USER_ANSWER,"essay text lost in progress snapshot");
        require(saved.get().get(one.questions().get(0).id()).revealed(),"model answer reveal not saved");
        int priorWrites=progressBooks.size();old.choiceButtons.get("X").doClick();
        equal(progressBooks.size(),priorWrites,"old card saved into another workbook");
        panel.showWorkbookList();panel.workbookButtons.get(one.id()).doClick();panel.openWorkbook(one,java.util.Map.of());
        equal(panel.cards.get(0).userAnswer(),USER_ANSWER,"in-session answer cache lost to stale disk data");
        panel.showWorkbookList();panel.workbookButtons.get(one.id()).doClick();panel.reset(12,"other");panel.setReady(true);
        panel.openWorkbook(one,java.util.Map.of());require(panel.cards.isEmpty(),"old workbook opened after PDF reset");
    }

    private static QuizWorkbook workbook(String id,QuizPanel.Theme theme,QuizQuestion question) {
        return new QuizWorkbook(id,DOC,theme.title+" 문제집",theme,"중",1,1700000000000L,12,.001,"",List.of(question));
    }

    private static void comparisonAndTutor() throws Exception {
        for(QuizQuestion.Type type:List.of(QuizQuestion.Type.SHORT_ANSWER,QuizQuestion.Type.ESSAY)) {
            QuizQuestion question=question(type);
            AtomicReference<QuizTutorRequest> sent=new AtomicReference<>();
            QuizQuestionCard card=new QuizQuestionCard(question,sent::set);
            equal(card.checkButton.getText(),"모범답안 보기","comparison action");
            require(!card.answerPanel.isVisible()&&!card.answerRevealed(),"answer initially exposed");
            card.answerInput.setText(USER_ANSWER);
            card.tutorButton.doClick();
            QuizTutorRequest request=sent.get();
            require(request!=null,"tutor did not receive request");
            equal(request.userAnswer(),USER_ANSWER,"current draft lost");
            equal(request.preferredPage(),7,"evidence page lost");
            require(request.prompt().contains("[작성하신 답변은 해설의 채점기준으로 N/10점 답변이에요.]"),"scored tutor opening lost");
            require(request.prompt().contains("허용 대안(필수 아님)")&&request.prompt().contains("중복 채점하지 마"),"optional/conditional rubric handling lost");
            JsonObject payload=JsonParser.parseString(request.prompt().substring(request.prompt().indexOf("[문제 정보]\n")+"[문제 정보]\n".length())).getAsJsonObject();
            equal(payload.get("userAnswer").getAsString(),USER_ANSWER,"serialized answer lost");
            JsonObject data=payload.getAsJsonObject("question");
            equal(data.get("documentId").getAsString(),DOC,"document ID lost");
            equal(data.get("stem").getAsString(),question.stem(),"stem lost");
            equal(data.get("answer").getAsString(),question.answer(),"model answer lost");
            equal(data.get("explanation").getAsString(),question.explanation(),"grading explanation lost");
            equal(data.getAsJsonArray("keyPoints").size(),question.keyPoints().size(),"grading criteria lost");
            equal(data.getAsJsonArray("evidence").get(0).getAsJsonObject().get("quote").getAsString(),"근거 원문 전체","evidence quote lost");
            card.checkButton.doClick();
            require(card.answerPanel.isVisible()&&card.answerRevealed(),"comparison did not reveal");
            equal(card.feedback.getText(),"내 답변과 모범답안을 비교해 보세요.","comparison feedback");
            require(!card.feedback.getText().contains("오답")&&!card.feedback.getText().contains("정답"),"self comparison graded answer");
            card.answerInput.setText("");
            card.tutorButton.doClick();
            equal(sent.get().userAnswer(),"","empty answer snapshot changed");
            require(sent.get().prompt().contains("점수를 만들거나 0점으로 판정하지 말고"),"missing answer received invented grade");
            card.checkButton.doClick();
            require(card.answerPanel.isVisible(),"empty answer cannot reveal model answer");
        }
        QuizQuestion mcq=question(QuizQuestion.Type.MCQ);
        String prompt=new QuizTutorRequest(mcq,"C").prompt();
        JsonObject data=JsonParser.parseString(prompt.substring(prompt.indexOf("[문제 정보]\n")+"[문제 정보]\n".length())).getAsJsonObject().getAsJsonObject("question");
        equal(data.getAsJsonArray("options").size(),4,"options lost");
        equal(data.getAsJsonArray("options").get(2).getAsJsonObject().get("explanation").getAsString(),"C의 이유","option explanation lost");
        require(new QuizTutorRequest(new QuizQuestion("preview",DOC,QuizQuestion.Type.OX,"","예시",List.of(),"O","",List.of(),List.of(),true),"").prompt().contains("화면 구성용 예시"),"preview provenance lost");
    }

    private static void objectiveCards() {
        for(QuizQuestion.Type type:List.of(QuizQuestion.Type.OX,QuizQuestion.Type.MCQ)) {
            QuizQuestionCard card=new QuizQuestionCard(question(type),ignored->{});
            require(!card.checkButton.isEnabled(),"objective check enabled without choice");
            String wrong=type==QuizQuestion.Type.OX?"X":"C";
            card.choiceButtons.get(wrong).doClick();card.checkButton.doClick();
            require(card.feedback.getText().contains("오답이에요"),"wrong objective answer not graded");
            card.choiceButtons.get(card.question.answer()).doClick();
            require(!card.answerPanel.isVisible()&&!card.feedback.isVisible(),"old verdict survived choice change");
            card.checkButton.doClick();equal(card.feedback.getText(),"정답이에요!","correct objective feedback");
        }
    }

    private static void staleDocumentAndScope() {
        QuizPanel panel=panel();
        List<QuizTutorRequest> sent=new ArrayList<>();
        panel.setTutorRequestHandler(sent::add);panel.setTutorReady(true);
        panel.showQuestions(List.of(question(QuizQuestion.Type.ESSAY)));
        QuizQuestionCard old=panel.cards.get(0);
        old.answerInput.setText(USER_ANSWER);old.tutorButton.doClick();
        require(sent.size()==1,"panel tutor routing failed");
        panel.setTutorReady(false);require(!old.tutorButton.isEnabled(),"busy tutor button enabled");
        panel.setTutorReady(true);
        panel.showQuestions(List.of(question(QuizQuestion.Type.SHORT_ANSWER)));
        old.tutorButton.doClick();require(sent.size()==1,"replaced card sent within the same document");
        panel.cards.get(0).tutorButton.doClick();require(sent.size()==2,"replacement card tutor routing failed");
        panel.showPreview();QuizQuestionCard closedPreview=panel.cards.get(0);
        panel.preview.doClick();require(panel.cards.isEmpty(),"preview did not close");
        closedPreview.tutorButton.doClick();require(sent.size()==2,"closed preview card sent within the same document");
        panel.reset(12,"new-document");panel.setReady(true);panel.setTutorReady(true);
        old.tutorButton.doClick();require(sent.size()==2,"stale card sent into a new document");
        try {panel.showQuestions(List.of(question(QuizQuestion.Type.ESSAY)));throw new AssertionError("foreign document accepted");}
        catch(IllegalArgumentException expected) {}
    }

    private static void render() throws Exception {
        QuizPanel panel=panel();panel.setTutorRequestHandler(ignored->{});panel.setTutorReady(true);
        panel.setGenerationRequestHandler(ignored->{});panel.setGenerationReady(true);
        for(int width:List.of(360,760)) {
            paint(panel,width,850,"setup-"+width+".png");
            assertThemeTextFits(panel);assertFlowRowsFit(panel);
            panel.settings.doClick();
            paint(panel,width,1000,"settings-"+width+".png");
            assertThemeTextFits(panel);assertFlowRowsFit(panel);
            panel.settings.doClick();
            panel.showPreview();
            for(QuizQuestionCard card:panel.cards) {
                if(card.question.selfComparison())card.answerInput.setText(USER_ANSWER);
                else card.choiceButtons.get(card.question.answer()).doClick();
                card.checkButton.doClick();
                int cardWidth=width-60;card.setSize(cardWidth,1);
                for(int pass=0;pass<4;pass++){card.setSize(cardWidth,card.getPreferredSize().height);layout(card);}
                paint(card,cardWidth,card.getPreferredSize().height,"card-"+card.question.type().name().toLowerCase()+"-"+width+".png");
                require(card.tutorButton.getWidth()>=card.tutorButton.getFontMetrics(card.tutorButton.getFont()).stringWidth(card.tutorButton.getText())+card.tutorButton.getInsets().left+card.tutorButton.getInsets().right,"tutor label clipped at "+width);
            }
            paint(panel,width,1000,"preview-"+width+".png");
            panel.preview.doClick();
            panel.setWorkbooks(List.of(workbook("render-one",QuizPanel.Theme.PRACTICE,question(QuizQuestion.Type.ESSAY)),
                workbook("render-two",QuizPanel.Theme.RECALL,question(QuizQuestion.Type.MCQ))));
            paint(panel,width,1100,"workbook-list-"+width+".png");
            assertThemeTextFits(panel);assertFlowRowsFit(panel);
            for(JButton open:panel.workbookButtons.values())require(open.getHeight()>28&&open.getWidth()>150,"workbook open action clipped");
            panel.workbookButtons.get("render-one").doClick();
            panel.cards.get(0).answerInput.setText(USER_ANSWER);panel.cards.get(0).checkButton.doClick();
            paint(panel,width,1300,"workbook-play-"+width+".png");
            require(panel.workbookBack.getWidth()>=panel.workbookBack.getFontMetrics(panel.workbookBack.getFont()).stringWidth(panel.workbookBack.getText())+panel.workbookBack.getInsets().left+panel.workbookBack.getInsets().right,"workbook back label clipped");
            panel.workbookBack.doClick();
        }
    }

    private static void liveGenerationPlaying() {
        QuizPanel panel=panel();panel.setGenerationReady(true);panel.setGenerationRequestHandler(request->{});
        panel.setWorkbookOpenHandler(book->panel.openWorkbook(book,java.util.Map.of()));
        panel.setGenerating(true,"출제 범위를 배분하고 있어요.");
        QuizQuestion first=question(QuizQuestion.Type.ESSAY),second=question(QuizQuestion.Type.SHORT_ANSWER);
        QuizWorkbook partial=new QuizWorkbook("live",DOC,"생성 중 문제집",QuizPanel.Theme.CONCEPT,"중",2,1,1,.001,"",List.of(first));
        panel.acceptGenerationSnapshot(partial);
        require(panel.workbookButtons.get("live").isEnabled(),"partial workbook must be playable during generation");
        require(!panel.generate.isEnabled(),"partial updates must not permit duplicate generation");
        panel.workbookButtons.get("live").doClick();
        require(panel.cards.size()==1&&panel.currentWorkbookId().equals("live"),"partial workbook did not open");
        QuizQuestionCard original=panel.cards.get(0);
        original.answerInput.setText(USER_ANSWER);original.checkButton.doClick();
        QuizWorkbook expanded=new QuizWorkbook("live",DOC,"생성 중 문제집",QuizPanel.Theme.CONCEPT,"중",2,1,2,.002,"",List.of(second,first));
        panel.acceptGenerationSnapshot(expanded);
        require(panel.cards.size()==1&&panel.studyView.questionCount()==2&&panel.cards.get(0)==original,"new arrivals must preserve the existing card instance");
        equal(original.answerInput.getText(),USER_ANSWER,"live updates lost typed answer");
        require(panel.generate.getText().contains("생성 중"),"partial update marked generation complete");
        panel.addWorkbook(expanded);
        require(panel.currentWorkbookId().equals("live")&&panel.cards.get(0)==original,"completion interrupted active solving");
        require(panel.generate.getText().contains("100%"),"final workbook must complete progress");
        panel.setGenerating(true,"새 문제집 생성 중");
        panel.workbookBack.doClick();panel.workbookButtons.get("live").doClick();
        require(panel.currentWorkbookId().equals("live")&&panel.cards.size()==1&&panel.studyView.questionCount()==2,"old workbook must remain playable during another generation");
        panel.studyView.select(1);QuizQuestionCard restored=panel.cards.getFirst();
        equal(restored.answerInput.getText(),USER_ANSWER,"switching workbook lost saved answer");
        panel.showGenerationFailure("취소했어요.");
        require(panel.currentWorkbookId().equals("live"),"cancellation interrupted existing workbook");
    }

    private static QuizQuestion question(QuizQuestion.Type type) {
        List<QuizQuestion.Option> options=type==QuizQuestion.Type.MCQ
            ?List.of(new QuizQuestion.Option("A","첫 번째 선택지","A의 이유"),
                new QuizQuestion.Option("B","두 번째 선택지","B의 이유"),
                new QuizQuestion.Option("C","세 번째 선택지","C의 이유"),
                new QuizQuestion.Option("D","네 번째 선택지","D의 이유")):List.of();
        String answer=type==QuizQuestion.Type.OX?"O":type==QuizQuestion.Type.MCQ?"B":"핵심 조건을 포함한 모범답안이에요.";
        return new QuizQuestion("fixture-"+type,DOC,type,"핵심 개념","문제의 조건을 읽고 답을 작성해 보세요.",
            options,answer,"문제의 핵심 조건과 근거를 설명해요.",type==QuizQuestion.Type.ESSAY?List.of("첫 번째 핵심","두 번째 핵심"):List.of(),
            List.of(new QuizQuestion.Evidence("source-7",7,"근거 원문 전체")),false);
    }
    private static JButton button(Container parent,String text) {
        for(Component child:parent.getComponents()) {
            if(child instanceof JButton button&&text.equals(button.getText()))return button;
            if(child instanceof Container nested) {JButton found=findButton(nested,text);if(found!=null)return found;}
        }
        throw new AssertionError("Missing button: "+text);
    }
    private static JButton findButton(Container parent,String text) {
        for(Component child:parent.getComponents()) {
            if(child instanceof JButton button&&text.equals(button.getText()))return button;
            if(child instanceof Container nested) {JButton found=findButton(nested,text);if(found!=null)return found;}
        }
        return null;
    }
    private static void assertThemeTextFits(QuizPanel panel) {
        panel.themeButtons.forEach((theme,button)->{
            Insets insets=button.getInsets();
            int needed=button.getFontMetrics(button.getFont()).stringWidth(button.getText())+insets.left+insets.right;
            require(button.getWidth()>=needed,"theme label clipped: "+theme+" needs "+needed+" has "+button.getWidth());
            require(button.getHeight()>=30,"theme button height collapsed: "+theme+" has "+button.getBounds());
            require(button.getParent().getHeight()>=button.getY()+button.getHeight(),"theme row height clipped: "+theme+" parent "+button.getParent().getBounds()+" button "+button.getBounds());
        });
    }
    private static void assertFlowRowsFit(Container parent) {
        if(parent.getLayout() instanceof FlowLayout && parent.isVisible()) {
            for(Component child:parent.getComponents())if(child.isVisible()&&child instanceof AbstractButton)
                require(child.getY()+child.getHeight()<=parent.getHeight(),"wrapped control clipped: "+((AbstractButton)child).getText());
        }
        for(Component child:parent.getComponents())if(child instanceof Container nested&&child.isVisible())assertFlowRowsFit(nested);
    }
    private static void paint(JComponent panel,int width,int height,String name) throws Exception {
        panel.setSize(width,Math.max(1,height));
        for(int pass=0;pass<8;pass++){invalidateTree(panel);layout(panel);}
        BufferedImage image=new BufferedImage(width,Math.max(1,height),BufferedImage.TYPE_INT_ARGB);
        Graphics2D graphics=image.createGraphics();panel.printAll(graphics);graphics.dispose();
        ImageIO.write(image,"png",output.resolve(name).toFile());
    }
    private static void layout(Container parent) {
        parent.doLayout();for(Component child:parent.getComponents())if(child instanceof Container nested)layout(nested);
    }
    private static void invalidateTree(Container parent) {
        for(Component child:parent.getComponents())if(child instanceof Container nested)invalidateTree(nested);
        parent.invalidate();
    }
    private static void equal(Object actual,Object expected,String label) {
        if(!expected.equals(actual))throw new AssertionError(label+": "+actual+" != "+expected);
    }
    private static void require(boolean condition,String message) {if(!condition)throw new AssertionError(message);}
}
