package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.MistWorkspaceTheme;
import dev.synesis.poc.ui.LibraryMotionClock;
import java.awt.*;
import java.awt.event.ComponentAdapter;
import java.awt.event.ComponentEvent;
import java.awt.event.MouseAdapter;
import java.awt.event.MouseEvent;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.function.Consumer;
import java.util.function.Supplier;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import javax.swing.event.DocumentEvent;
import javax.swing.event.DocumentListener;

/** Local question interaction; generation and tutor transport are supplied by the workspace. */
final class QuizQuestionCard extends JPanel {
    static final String TUTOR_LABEL = "AI멘토에게 이 문제 해설 요청하기";
    final QuizQuestion question;
    final JButton tutorButton = new JButton(TUTOR_LABEL);
    final JButton checkButton;
    final JButton unknownButton=QuizPlayDesign.button("모르겠어요",false);
    final JButton bookmarkButton=QuizPlayDesign.button("문제 체크",false);
    private final JLabel questionNumber=MistWorkspaceTheme.label("",12,QuizPlayDesign.MUTED,Font.BOLD);
    final JTextArea answerInput = new JTextArea();
    final JPanel answerPanel = QuizPlayDesign.panel(new StackLayout(14),24);
    final JLabel feedback = new QuizPlayDesign.Banner();
    final Map<String,JRadioButton> choiceButtons = new LinkedHashMap<>();
    private final ButtonGroup choices = new ButtonGroup();
    private final Consumer<QuizTutorRequest> onTutor;
    private Supplier<List<QuizConceptLinks.Target>> conceptLinks=List::of;
    private Consumer<QuizConceptLinks.Target> onConcept=ignored->{};
    private QuizRichText ownAnswer;
    private boolean revealed;
    private boolean restoring;
    private boolean bookmarked,skipped;
    private final boolean focused;
    private final int bodyFont;
    private final JPanel submit=new JPanel(new GridLayout(1,2,10,0));
    private final Map<String,ChoiceRow> choiceRows=new LinkedHashMap<>();
    private Consumer<QuizWorkbook.Answer> onAnswer=ignored->{};
    private int previousWidth = -1;

    QuizQuestionCard(QuizQuestion question, Consumer<QuizTutorRequest> onTutor) {
        this(question, 1, onTutor);
    }

    QuizQuestionCard(QuizQuestion question, int number, Consumer<QuizTutorRequest> onTutor) {
        this(question,number,onTutor,false);
    }

    QuizQuestionCard(QuizQuestion question,int number,Consumer<QuizTutorRequest> onTutor,boolean focused) {
        this(question,number,onTutor,focused,16);
    }
    QuizQuestionCard(QuizQuestion question,int number,Consumer<QuizTutorRequest> onTutor,boolean focused,int bodyFont) {
        super(new StackLayout(16));
        this.bodyFont=Math.max(6,Math.min(64,bodyFont));
        this.question = Objects.requireNonNull(question);
        this.onTutor = Objects.requireNonNull(onTutor);
        this.focused=focused;
        checkButton = QuizPlayDesign.button(question.selfComparison() ? "모범답안 보기" : "정답 확인",true);
        setOpaque(false);
        JPanel surface=QuizPlayDesign.panel(new StackLayout(focused?24:18),focused?22:24,Color.WHITE);
        add(surface);
        setAlignmentX(Component.LEFT_ALIGNMENT);
        setMinimumSize(new Dimension(0, 0));

        JPanel header = new JPanel(new BorderLayout(8, 0));
        header.setOpaque(false);
        setQuestionNumber(number);header.add(questionNumber,BorderLayout.WEST);
        if (question.preview()) {
            JLabel badge = MistWorkspaceTheme.badge("화면 예시");
            badge.setBorder(new EmptyBorder(4, 8, 4, 8));
            header.add(badge, BorderLayout.EAST);
        } else {
            bookmarkButton.setIcon(QuizPlayDesign.icon("bookmark",17));
            bookmarkButton.addActionListener(e->{bookmarked=!bookmarked;refreshBookmark();if(!restoring)onAnswer.accept(snapshot());});
            refreshBookmark();header.add(bookmarkButton,BorderLayout.EAST);
        }
        surface.add(header);
        var sections=QuizStemPresentation.sections(question.stem());
        if(question.type()==QuizQuestion.Type.OX){
            JTextArea guide=new JTextArea(sections.passage().isBlank()?QuizStemPresentation.OX_GUIDE:QuizStemPresentation.OX_PASSAGE_GUIDE);
            guide.setName("quiz-ox-guide");guide.setEditable(false);guide.setFocusable(false);
            guide.setOpaque(false);guide.setLineWrap(true);guide.setWrapStyleWord(true);
            guide.setFont(MistWorkspaceTheme.font(Font.PLAIN,Math.min(64,this.bodyFont+2)));guide.setForeground(QuizPlayDesign.TEXT);
            guide.putClientProperty("synesis.preserveFont",true);surface.add(guide);
        }
        if(!sections.passage().isBlank()){
            JPanel passage=QuizPlayDesign.panel(new StackLayout(8),14,QuizPlayDesign.SOFT);
            passage.setName("quiz-question-passage");
            passage.add(MistWorkspaceTheme.label("제시문",12,QuizPlayDesign.MUTED,Font.PLAIN));
            passage.add(new QuizRichText(sections.passage(),this.bodyFont,QuizPlayDesign.SOFT,false,QuizPlayDesign.TEXT));
            surface.add(passage);
        }
        surface.add(MistWorkspaceTheme.label(question.type()==QuizQuestion.Type.OX?"판단할 진술":"문제",12,QuizPlayDesign.MUTED,Font.PLAIN));
        QuizRichText stem=new QuizRichText(question.type()==QuizQuestion.Type.OX?QuizStemPresentation.ox(sections.question()):sections.question(),focused?Math.min(64,this.bodyFont+2):this.bodyFont,Color.WHITE,false,QuizPlayDesign.TEXT);
        stem.setName("quiz-question-stem");
        if(focused){
            stem.setBorder(new EmptyBorder(8,0,6,0));
        }
        surface.add(stem);
        if(!question.warnings().isEmpty()) {
            QuizRichText notice=new QuizRichText("확인 안내: "+String.join(" · ",question.warnings()),
                13,Color.WHITE,false,new Color(145,85,25));
            notice.setName("quiz-question-warning");surface.add(notice);
        }

        if (question.selfComparison()) {
            answerInput.setRows(question.type() == QuizQuestion.Type.ESSAY ? 5 : 2);
            answerInput.setColumns(20);
            answerInput.setLineWrap(true);
            answerInput.setWrapStyleWord(true);
            answerInput.setFont(MistWorkspaceTheme.font(Font.PLAIN, this.bodyFont));
            answerInput.setForeground(MistWorkspaceTheme.INK);
            answerInput.setBackground(MistWorkspaceTheme.SOFT);
            answerInput.setBorder(new EmptyBorder(10, 12, 10, 12));
            answerInput.getAccessibleContext().setAccessibleName("내 답변");
            answerInput.putClientProperty("synesis.preserveFont", true);
            // Share the quiz's wheel handoff when the answer has no scrollable overflow.
            QuizScrollPane scroll = new QuizScrollPane(answerInput,
                JScrollPane.VERTICAL_SCROLLBAR_AS_NEEDED,JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
            scroll.setBorder(BorderFactory.createLineBorder(MistWorkspaceTheme.LINE));
            scroll.setHorizontalScrollBarPolicy(JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
            surface.add(scroll);
            answerInput.getDocument().addDocumentListener(new DocumentListener() {
                public void insertUpdate(DocumentEvent event) { answerChanged(); }
                public void removeUpdate(DocumentEvent event) { answerChanged(); }
                public void changedUpdate(DocumentEvent event) { answerChanged(); }
            });
        } else {
            JPanel rows = question.type()==QuizQuestion.Type.OX&&focused?new JPanel(new ResponsiveColumns(12)):column(10);
            rows.setOpaque(false);
            if (question.type() == QuizQuestion.Type.OX) {
                rows.add(choice("O", "O", "참"));
                rows.add(choice("X", "X", "거짓"));
            } else {
                String[] labels = {"①", "②", "③", "④"};
                for (int i=0; i<question.options().size(); i++) {
                    QuizQuestion.Option option = question.options().get(i);
                    rows.add(choice(option.id(), labels[i], option.text()));
                }
            }
            surface.add(rows);
        }

        checkButton.setEnabled(question.selfComparison());
        checkButton.addActionListener(event -> revealAnswer());
        unknownButton.addActionListener(event->{skipped=true;revealAnswer();});
        submit.setOpaque(false);submit.add(checkButton);submit.add(unknownButton);surface.add(submit);
        feedback.setVisible(false);
        answerPanel.setVisible(false);
        add(answerPanel);

        MistWorkspaceTheme.button(tutorButton, true);
        tutorButton.setFont(MistWorkspaceTheme.font(Font.PLAIN, 11));
        if(focused){tutorButton.setText("튜터에게 이 문제 해설 요청하기");tutorButton.setIcon(QuizPlayDesign.icon("lightbulb",15));}
        tutorButton.getAccessibleContext().setAccessibleName(TUTOR_LABEL);
        tutorButton.addActionListener(event -> this.onTutor.accept(new QuizTutorRequest(this.question, userAnswer())));
        surface.add(tutorButton);
        addComponentListener(new ComponentAdapter() {
            @Override public void componentResized(ComponentEvent event) {
                if (previousWidth != getWidth()) {
                    previousWidth = getWidth();
                    revalidate();
                }
            }
        });
    }

    String userAnswer() {
        if (question.selfComparison()) return answerInput.getText();
        return choices.getSelection() == null ? "" : choices.getSelection().getActionCommand();
    }

    boolean answerRevealed() { return revealed; }
    void setQuestionNumber(int number){questionNumber.setText(String.format("%02d · %s",number,question.type().label()));}
    void setTutorReady(boolean ready) { tutorButton.setEnabled(ready); }
    void setConceptNavigation(Supplier<List<QuizConceptLinks.Target>> links,Consumer<QuizConceptLinks.Target> handler) {
        conceptLinks=Objects.requireNonNull(links);onConcept=Objects.requireNonNull(handler);
    }
    QuizWorkbook.Answer snapshot() {return new QuizWorkbook.Answer(userAnswer(),revealed,bookmarked,skipped);}
    void setAnswerChangeHandler(Consumer<QuizWorkbook.Answer> handler) {onAnswer=Objects.requireNonNull(handler);}
    void restore(QuizWorkbook.Answer answer) {
        restoring=true;
        try {
            revealed=false;skipped=answer!=null&&answer.skipped();bookmarked=answer!=null&&answer.bookmarked();refreshBookmark();
            ownAnswer=null;answerInput.setEditable(true);answerPanel.setVisible(false);feedback.setVisible(false);submit.setVisible(true);
            choiceButtons.values().forEach(button->button.setEnabled(true));
            if(question.selfComparison())answerInput.setText(answer==null?"":answer.answer());
            else {
                choices.clearSelection();
                if(answer!=null&&choiceButtons.containsKey(answer.answer()))choiceButtons.get(answer.answer()).setSelected(true);
                checkButton.setEnabled(!userAnswer().isEmpty());
            }
            if(answer!=null&&answer.revealed())revealAnswer();
            refreshChoices();
        } finally {restoring=false;}
        revalidate();repaint();
    }
    private void answerChanged() {refreshOwnAnswer();if(!restoring)onAnswer.accept(snapshot());}

    private void refreshBookmark(){
        bookmarkButton.setSelected(bookmarked);bookmarkButton.setText(bookmarked?"체크됨":"문제 체크");
        bookmarkButton.setForeground(bookmarked?Color.WHITE:QuizPlayDesign.MUTED);
        bookmarkButton.getAccessibleContext().setAccessibleName(bookmarked?"문제 체크 해제":"문제 체크하기");
    }

    private JPanel choice(String id, String label, String text) {
        boolean ox=question.type()==QuizQuestion.Type.OX;
        ChoiceRow row = new ChoiceRow(id);
        choiceRows.put(id,row);
        row.setOpaque(false);
        row.setBorder(new EmptyBorder(focused?18:14,16,focused?18:14,16));
        JRadioButton radio = ox?new OxChoiceButton(id,label,text):new JRadioButton();
        if(!ox){radio.setIcon(new ChoiceIcon(id,label));radio.setSelectedIcon(new ChoiceIcon(id,label));radio.setDisabledIcon(new ChoiceIcon(id,label));radio.setDisabledSelectedIcon(new ChoiceIcon(id,label));}
        radio.setActionCommand(id);
        radio.setOpaque(false);
        radio.setFont(MistWorkspaceTheme.font(ox?Font.BOLD:Font.PLAIN,bodyFont));
        radio.setForeground(MistWorkspaceTheme.TEXT);
        radio.putClientProperty("synesis.preserveFont", true);
        radio.setBorder(new EmptyBorder(0, 0, 0, 0));
        radio.setVerticalAlignment(ox?SwingConstants.CENTER:SwingConstants.TOP);
        radio.getAccessibleContext().setAccessibleName(label + " " + text);
        choices.add(radio);
        choiceButtons.put(id, radio);
        radio.addActionListener(event -> {
            revealed = false;skipped=false;
            answerPanel.setVisible(false);
            feedback.setVisible(false);
            checkButton.setEnabled(true);
            refreshChoices();
            revalidate();
            if(!restoring)onAnswer.accept(snapshot());
        });
        row.addMouseListener(new MouseAdapter(){@Override public void mouseClicked(MouseEvent e){if(SwingUtilities.isLeftMouseButton(e)&&radio.isEnabled())radio.doClick();}});
        MouseAdapter hover=new MouseAdapter(){
            @Override public void mouseEntered(MouseEvent e){row.hover(true);}
            @Override public void mouseExited(MouseEvent e){row.hover(false);}
        };
        row.addMouseListener(hover);radio.addMouseListener(hover);
        if(ox){row.add(radio,BorderLayout.CENTER);return row;}
        QuizRichText body = markdown(text, bodyFont);
        MouseAdapter select=new MouseAdapter() {
            @Override public void mouseClicked(MouseEvent event) {
                if (SwingUtilities.isLeftMouseButton(event) && event.getClickCount() == 1 && radio.isEnabled()) radio.doClick();
            }
        };
        for(StudyHtmlPane pane:body.textPanes()){pane.addMouseListener(select);pane.addMouseListener(hover);}
        row.add(radio);
        row.add(body);
        return row;
    }

    private void revealAnswer() {
        if (!question.selfComparison() && userAnswer().isEmpty()&&!skipped) return;
        revealed = true;
        if(focused)answerInput.setEditable(false);
        submit.setVisible(!focused);
        if(focused)choiceButtons.values().forEach(button->button.setEnabled(false));
        refreshChoices();
        answerPanel.removeAll();
        if(focused)answerPanel.add(MistWorkspaceTheme.label("정답과 해설",17,QuizPlayDesign.INK,Font.BOLD));
        answerPanel.add(feedback);
        if (question.selfComparison()) {
            feedback.putClientProperty("quiz.correct",null);feedback.setIcon(null);
            feedback.setText("내 답변과 모범답안을 비교해 보세요.");
            feedback.setForeground(MistWorkspaceTheme.MUTED);
            JPanel comparison = new JPanel(new ResponsiveColumns(14));
            comparison.setOpaque(false);
            JPanel mine = column(6), model = column(6);
            mine.add(MistWorkspaceTheme.label("내 답변", 12, MistWorkspaceTheme.MUTED, Font.BOLD));
            ownAnswer = markdown(ownAnswerText(), bodyFont);
            mine.add(ownAnswer);
            model.add(MistWorkspaceTheme.label(question.answerContractVersion().isBlank()?"모범답안":"예시 답안", 12, MistWorkspaceTheme.MUTED, Font.BOLD));
            model.add(markdown(question.answer(), bodyFont));
            comparison.add(mine);
            comparison.add(model);
            answerPanel.add(comparison);
            if (!question.keyPoints().isEmpty()) {
                answerPanel.add(MistWorkspaceTheme.label(question.answerContractVersion().isBlank()?"포함할 핵심 내용":"공통 요구와 조건별 비교 기준", 12, MistWorkspaceTheme.MUTED, Font.BOLD));
                answerPanel.add(markdown("- " + String.join("\n- ", question.keyPoints()), bodyFont));
            }
        } else {
            boolean correct = !skipped&&question.answer().equals(userAnswer());
            feedback.putClientProperty("quiz.correct",correct);feedback.setIcon(QuizPlayDesign.icon(correct?"check":"x",18));
            feedback.setText(correct ? "정답이에요!" : skipped?"오답이에요 · 모르겠어요로 넘긴 문제예요. 해설을 확인해 보세요.":"오답이에요 · 정답과 해설을 확인해 보세요.");
            feedback.setForeground(correct?QuizPlayDesign.CORRECT:QuizPlayDesign.INCORRECT);
            answerPanel.add(solutionSection("정답",correctAnswerText()));
        }
        if (!question.explanation().isBlank()) {
            answerPanel.add(solutionSection("해설",question.explanation()));
        }
        if (question.type() == QuizQuestion.Type.MCQ) {
            JPanel notes=focused?new JPanel(new NotesLayout()):answerPanel;
            if(focused)notes.setOpaque(false);
            for (int i=0; i<question.options().size(); i++) {
                QuizQuestion.Option option = question.options().get(i);
                if (!option.explanation().isBlank()) {
                    JPanel note=focused?column(8):notes;
                    boolean right=option.id().equals(question.answer());
                    Color tone=right?QuizPlayDesign.CORRECT:QuizPlayDesign.INCORRECT;
                    if(focused){note.setOpaque(true);note.setBackground(right?QuizPlayDesign.CORRECT_SOFT:QuizPlayDesign.INCORRECT_SOFT);note.setBorder(new EmptyBorder(13,13,13,13));}
                    note.add(MistWorkspaceTheme.label("선지 " + (i+1)+(right?" · 정답":" · 오답"), 12, tone, Font.BOLD));
                    note.add(markdown(option.explanation(), bodyFont));
                    if(focused)notes.add(note);
                }
            }
            if(focused&&notes.getComponentCount()>0)answerPanel.add(notes);
        }
        List<Integer> pages = question.evidence().stream().map(QuizQuestion.Evidence::page)
            .filter(page -> page > 0).distinct().toList();
        boolean savedConcept=question.evidence().stream().anyMatch(item->item.sourceKind().equals("saved_concept"));
        String sourceLabel=savedConcept?"출제 근거: 개념 정리":"출제 근거: PDF 자료";
        // Concept titles can contain the answer, so reveal them with the solution.
        if (!question.concept().isBlank()) {
            List<QuizConceptLinks.Target> links=question.preview()?List.of():conceptLinks.get();
            if(links.isEmpty())answerPanel.add(markdown("관련 개념: " + question.concept(), 12));
            else {
                JPanel related=column(4);
                related.add(MistWorkspaceTheme.label("관련 개념:",12,MistWorkspaceTheme.MUTED,Font.PLAIN));
                JPanel tags=new QuizPanel.WrapRow(4,4);
                for(var target:links) {
                    JButton tag=new JButton("# "+target.title()) {
                        @Override public Dimension getPreferredSize() {
                            Dimension size=super.getPreferredSize();
                            if(getParent()!=null&&getParent().getWidth()>8)size.width=Math.min(size.width,getParent().getWidth()-8);
                            return size;
                        }
                    };
                    tag.setName("quiz-concept:"+target.index());
                    MistWorkspaceTheme.button(tag,true);
                    tag.setForeground(QuizPlayDesign.TEXT);
                    tag.setFont(MistWorkspaceTheme.font(Font.PLAIN,12));
                    tag.setToolTipText("개념 정리에서 "+target.title()+" 보기");
                    tag.getAccessibleContext().setAccessibleName("관련 개념: "+target.title()+" · 개념 정리로 이동");
                    tag.addActionListener(event->{if(revealed&&answerPanel.isVisible())onConcept.accept(target);});
                    tags.add(tag);
                }
                related.add(tags);answerPanel.add(related);
            }
        }
        if (!question.evidence().isEmpty()) answerPanel.add(markdown(sourceLabel
            +(pages.isEmpty()?"":" · 관련 "+String.join(" · ", pages.stream().map(page -> "p." + page).toList())),12));
        if(question.evidence().stream().anyMatch(QuizQuestion.Evidence::standardKnowledgeUsed))
            answerPanel.add(markdown("개념 정리에 포함된 보충 지식이 있어요.",12));
        feedback.setVisible(true);
        answerPanel.setVisible(true);
        revalidate();
        repaint();
        if(!restoring)onAnswer.accept(snapshot());
    }

    private String correctAnswerText() {
        if (question.type() == QuizQuestion.Type.OX) return question.answer();
        for (int i=0; i<question.options().size(); i++) {
            QuizQuestion.Option option = question.options().get(i);
            if (option.id().equals(question.answer())) {
                String text=option.text(),leading=text.stripLeading();
                // A fence must start its own line; a prefixed option label otherwise turns it into inline code.
                boolean codeBlock=leading.startsWith("```")||leading.startsWith("~~~")||text.startsWith("    ")||text.startsWith("\t");
                return new String[]{"①","②","③","④"}[i]+(codeBlock?"\n\n":" ")+text;
            }
        }
        return question.answer();
    }

    private String ownAnswerText() {
        return answerInput.getText().isBlank() ? "아직 입력한 답변이 없어요." : answerInput.getText();
    }
    private void refreshOwnAnswer() {
        if (!revealed || ownAnswer == null || !question.selfComparison()) return;
        Container parent = ownAnswer.getParent();
        if (parent == null) return;
        int index = parent.getComponentZOrder(ownAnswer);
        parent.remove(ownAnswer);
        ownAnswer = markdown(ownAnswerText(), bodyFont);
        parent.add(ownAnswer, index);
        parent.revalidate();
        answerPanel.revalidate();
        revalidate();
    }

    private void refreshChoices(){choiceRows.values().forEach(JPanel::repaint);}

    private final class ChoiceRow extends JPanel implements LibraryMotionClock.Task {
        final String id;private double amount,from,target;private long started;
        ChoiceRow(String id){super(question.type()==QuizQuestion.Type.OX?new BorderLayout():new ChoiceLayout());this.id=id;}
        void hover(boolean value){
            double next=value&&(!focused||!revealed)?1:0;
            if(next==target)return;from=amount;target=next;started=System.nanoTime();
            if(!isShowing()||LibraryMotionClock.reduced()||!LibraryMotionClock.add(this)){amount=target;repaint();}
        }
        public boolean advance(long now){
            if(!isShowing()){amount=target;return false;}
            double t=Math.min(1,(now-started)/150_000_000d);amount=from+(target-from)*LibraryMotionClock.ease(t);repaint();return t<1;
        }
        @Override public void paint(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();try{
                g.translate(0,-amount);super.paint(g);
            }finally{g.dispose();}
        }
        @Override protected void paintComponent(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();try{
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                boolean selected=id.equals(userAnswer()),correct=revealed&&id.equals(question.answer()),wrong=revealed&&selected&&!correct;
                g.setColor(correct?QuizPlayDesign.CORRECT_SOFT:wrong?QuizPlayDesign.INCORRECT_SOFT:selected?QuizPlayDesign.SOFT:Color.WHITE);g.fillRoundRect(1,1,getWidth()-2,getHeight()-2,24,24);
                g.setColor(correct?QuizPlayDesign.CORRECT:wrong?QuizPlayDesign.INCORRECT:selected?QuizPlayDesign.INK:amount>0?new Color(0x8c8c8c):QuizPlayDesign.LINE);
                g.setStroke(wrong?new BasicStroke(1,0,0,10,new float[]{3,3},0):new BasicStroke(selected||correct?1.7f:1));
                g.drawRoundRect(1,1,getWidth()-3,getHeight()-3,24,24);
            }finally{g.dispose();}super.paintComponent(graphics);
        }
        @Override public void removeNotify(){LibraryMotionClock.remove(this);amount=target=0;super.removeNotify();}
    }
    /** OX needs only a native centered label; keep its O/X identifier visible after grading. */
    private final class OxChoiceButton extends JRadioButton {
        private final String id,symbol,caption;
        OxChoiceButton(String id,String symbol,String caption){super(symbol+" "+caption);this.id=id;this.symbol=symbol;this.caption=caption;}
        @Override public Dimension getPreferredSize(){
            FontMetrics metrics=getFontMetrics(getFont());return new Dimension(metrics.stringWidth(getText())+72,Math.max(32,metrics.getHeight()));
        }
        @Override protected void paintComponent(Graphics graphics){
            Graphics2D g=(Graphics2D)graphics.create();try{
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
                boolean correct=revealed&&id.equals(question.answer()),wrong=revealed&&isSelected()&&!correct;
                Color tone=correct?QuizPlayDesign.CORRECT:wrong?QuizPlayDesign.INCORRECT:QuizPlayDesign.INK;
                int badgeY=(getHeight()-32)/2;
                g.setColor(correct||wrong?tone:QuizPlayDesign.SOFT);g.fillRoundRect(0,badgeY,32,32,10,10);
                g.setFont(getFont());FontMetrics metrics=g.getFontMetrics();int y=(getHeight()-metrics.getHeight())/2+metrics.getAscent();
                g.setColor(correct||wrong?Color.WHITE:QuizPlayDesign.TEXT);g.drawString(symbol,(32-metrics.stringWidth(symbol))/2,y);
                g.setColor(tone);g.drawString(caption,(getWidth()-metrics.stringWidth(caption))/2,y);
                if(correct)QuizPlayDesign.icon("check",18).paintIcon(this,g,getWidth()-20,(getHeight()-18)/2);
                if(isFocusOwner())g.drawRoundRect(1,1,getWidth()-3,getHeight()-3,8,8);
            }finally{g.dispose();}
        }
    }
    private final class ChoiceIcon implements Icon {
        private final String id,label;
        ChoiceIcon(String id,String label){this.id=id;this.label=label;}
        public int getIconWidth(){return 28;}public int getIconHeight(){return 28;}
        public void paintIcon(Component c,Graphics graphics,int x,int y){
            Graphics2D g=(Graphics2D)graphics.create();try{
                g.translate(x,y);g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                boolean correct=revealed&&id.equals(question.answer()),selected=id.equals(userAnswer());
                g.setColor(correct||selected?QuizPlayDesign.INK:Color.WHITE);g.fillOval(1,1,25,25);
                g.setColor(correct||selected?QuizPlayDesign.INK:QuizPlayDesign.LINE);g.drawOval(1,1,25,25);
                g.setColor(correct||selected?Color.WHITE:QuizPlayDesign.MUTED);
                if(correct){g.translate(5,5);g.scale(18/24d,18/24d);g.setStroke(new BasicStroke(1.8f));g.drawLine(5,12,9,16);g.drawLine(9,16,19,6);}
                else {String text=switch(label){case "①"->"1";case "②"->"2";case "③"->"3";case "④"->"4";default->label;};
                    g.setFont(MistWorkspaceTheme.font(Font.BOLD,12));FontMetrics fm=g.getFontMetrics();g.drawString(text,(28-fm.stringWidth(text))/2,(28-fm.getHeight())/2+fm.getAscent());}
            }finally{g.dispose();}
        }
    }

    private static JPanel column(int gap) {
        JPanel panel = new JPanel(new StackLayout(gap));
        panel.setOpaque(false);
        panel.setMinimumSize(new Dimension(0, 0));
        return panel;
    }
    private JPanel solutionSection(String title,String body) {
        JPanel section=column(10);
        boolean answer=title.equals("정답");
        Color accent=answer?QuizPlayDesign.CORRECT:QuizPlayDesign.EXPLANATION;
        section.setBorder(BorderFactory.createCompoundBorder(BorderFactory.createMatteBorder(0,3,0,0,accent),new EmptyBorder(4,12,6,0)));
        section.add(MistWorkspaceTheme.label(title,focused&&title.equals("해설")?18:12,accent,Font.BOLD));
        QuizRichText content=new QuizRichText(body,bodyFont,Color.WHITE,answer,answer?QuizPlayDesign.CORRECT:QuizPlayDesign.TEXT);
        section.add(content);
        return section;
    }

    private static QuizRichText markdown(String value,int font){return new QuizRichText(value,font);}

    @Override public Dimension getMaximumSize() {
        return new Dimension(Integer.MAX_VALUE, getPreferredSize().height);
    }

    private static final class ChoiceLayout implements LayoutManager {
        public void addLayoutComponent(String name, Component component) {}
        public void removeLayoutComponent(Component component) {}
        public Dimension minimumLayoutSize(Container parent) { return new Dimension(0, 0); }
        public Dimension preferredLayoutSize(Container parent) {
            int width = parent.getWidth() > 0 ? parent.getWidth() : 600;
            Insets insets = parent.getInsets();
            int available = Math.max(1, width-insets.left-insets.right);
            Component radio = parent.getComponent(0), body = parent.getComponent(1);
            int radioWidth = radio.getPreferredSize().width;
            body.setSize(Math.max(1, available-radioWidth-8), Math.max(1, body.getHeight()));
            return new Dimension(width, Math.max(radio.getPreferredSize().height, body.getPreferredSize().height)
                +insets.top+insets.bottom);
        }
        public void layoutContainer(Container parent) {
            Insets insets = parent.getInsets();
            Component radio = parent.getComponent(0), body = parent.getComponent(1);
            int radioWidth = radio.getPreferredSize().width;
            int bodyWidth = Math.max(1, parent.getWidth()-insets.left-insets.right-radioWidth-8);
            radio.setBounds(insets.left, insets.top, radioWidth, radio.getPreferredSize().height);
            body.setSize(bodyWidth, Math.max(1, body.getHeight()));
            body.setBounds(insets.left+radioWidth+8, insets.top, bodyWidth, body.getPreferredSize().height);
            if (body instanceof Container nested && !nested.isValid()) nested.doLayout();
        }
    }

    /** Width-first measurement gives the existing HTML/math viewports room to wrap locally. */
    static final class StackLayout implements LayoutManager {
        private final int gap;
        StackLayout(int gap) { this.gap = gap; }
        public void addLayoutComponent(String name, Component component) {}
        public void removeLayoutComponent(Component component) {}
        public Dimension minimumLayoutSize(Container parent) { return new Dimension(0, 0); }
        public Dimension preferredLayoutSize(Container parent) {
            Insets insets = parent.getInsets();
            int width = parent.getWidth() > 0 ? parent.getWidth() : parent.getParent() != null && parent.getParent().getWidth() > 0
                ? parent.getParent().getWidth() : 600;
            int available = Math.max(1, width-insets.left-insets.right), height = insets.top+insets.bottom, count=0;
            for (Component child : parent.getComponents()) if (child.isVisible()) {
                child.setSize(available, Math.max(1, child.getHeight()));
                height += child.getPreferredSize().height;
                if (count++ > 0) height += gap;
            }
            return new Dimension(width, height);
        }
        public void layoutContainer(Container parent) {
            Insets insets = parent.getInsets();
            int available = Math.max(1, parent.getWidth()-insets.left-insets.right), y=insets.top;
            for (Component child : parent.getComponents()) if (child.isVisible()) {
                child.setSize(available, Math.max(1, child.getHeight()));
                int height = child.getPreferredSize().height;
                child.setBounds(insets.left, y, available, height);
                if (child instanceof Container nested && !nested.isValid()) nested.doLayout();
                y += height+gap;
            }
        }
    }

    private static final class NotesLayout implements LayoutManager {
        public void addLayoutComponent(String name,Component c){}public void removeLayoutComponent(Component c){}
        public Dimension minimumLayoutSize(Container p){return new Dimension(0,0);}
        public Dimension preferredLayoutSize(Container p){return arrange(p,false);}
        public void layoutContainer(Container p){arrange(p,true);}
        private Dimension arrange(Container p,boolean apply){
            int width=p.getWidth()>0?p.getWidth():600,columns=width>=600?2:1,gap=10,columnWidth=Math.max(1,(width-(columns-1)*gap)/columns),y=0;
            Component[] children=p.getComponents();
            for(int i=0;i<children.length;i+=columns){
                int height=0;for(int j=i;j<Math.min(children.length,i+columns);j++){children[j].setSize(columnWidth,Math.max(1,children[j].getHeight()));height=Math.max(height,children[j].getPreferredSize().height);}
                if(apply)for(int j=i;j<Math.min(children.length,i+columns);j++){children[j].setBounds((j-i)*(columnWidth+gap),y,columnWidth,height);if(children[j] instanceof Container c)c.doLayout();}
                y+=height+gap;
            }
            return new Dimension(width,Math.max(0,y-gap));
        }
    }

    /** Wide answers sit side by side; narrow cards retain both full answers in vertical order. */
    private static final class ResponsiveColumns implements LayoutManager {
        private final int gap;
        ResponsiveColumns(int gap) { this.gap = gap; }
        public void addLayoutComponent(String name, Component component) {}
        public void removeLayoutComponent(Component component) {}
        public Dimension minimumLayoutSize(Container parent) { return new Dimension(0, 0); }
        public Dimension preferredLayoutSize(Container parent) {
            int width = parent.getWidth() > 0 ? parent.getWidth() : 600;
            boolean wide = width >= 560;
            int columnWidth = wide ? Math.max(1, (width-gap)/2) : width, height=0;
            for (Component child : parent.getComponents()) {
                child.setSize(columnWidth, Math.max(1, child.getHeight()));
                height = wide ? Math.max(height, child.getPreferredSize().height) : height+child.getPreferredSize().height;
            }
            if (!wide && parent.getComponentCount() > 1) height += gap;
            return new Dimension(width, height);
        }
        public void layoutContainer(Container parent) {
            int width = parent.getWidth();
            boolean wide = width >= 560;
            int columnWidth = wide ? Math.max(1, (width-gap)/2) : width, x=0, y=0;
            for (Component child : parent.getComponents()) {
                child.setSize(columnWidth, Math.max(1, child.getHeight()));
                int height = child.getPreferredSize().height;
                child.setBounds(x, y, columnWidth, height);
                if (child instanceof Container nested) nested.doLayout();
                if (wide) x += columnWidth+gap;
                else y += height+gap;
            }
        }
    }
}
