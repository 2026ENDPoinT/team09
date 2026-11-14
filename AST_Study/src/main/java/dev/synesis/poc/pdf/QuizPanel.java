package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.MistWorkspaceTheme;
import dev.synesis.poc.ui.LayoutMotionPanel;
import dev.synesis.poc.ui.SmoothScrollPane;
import dev.synesis.poc.ui.StudyTheme;

import javax.swing.*;
import javax.swing.border.EmptyBorder;
import java.awt.*;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;
import java.util.*;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.function.BiConsumer;
import java.util.function.Consumer;
import java.util.function.Function;

/** Shared quiz setup, explicit generation requests, and question views. Provider calls live outside the UI. */
final class QuizPanel extends JPanel {
    enum Theme {
        CONCEPT("개념 완성 N제", "핵심 정의와 조건, 비슷한 개념의 차이를 정리해요."),
        UNDERSTANDING("이해 확인 N제", "이유를 설명하고, 배운 내용을 사례에 적용해봐요."),
        PRACTICE("실전 N제", "낯선 상황과 복합 조건에 도전하는 고난도 실전 문제집이에요."),
        RECALL("암기 확인 N제", "핵심 용어와 특징, 구성과 순서를 떠올려봐요.");
        final String title, description;
        Theme(String title, String description) { this.title=title; this.description=description; }
        String profileTargetDescription() {
            return this==CONCEPT?"기본 개념 확인":"일반·심화 목표 5:5";
        }
    }

    /** One shared configuration for every theme. */
    record Configuration(int start, int end, String difficulty, Set<QuizQuestion.Type> types, String instructions) {
        Configuration {
            if(start<1 || end<start)throw new IllegalArgumentException("시작 쪽과 마지막 쪽을 확인해 주세요.");
            if(!LEVELS.contains(difficulty))throw new IllegalArgumentException("난이도를 선택해 주세요.");
            if(types==null || types.isEmpty())throw new IllegalArgumentException("문제 형식을 하나 이상 선택해 주세요.");
            types=Set.copyOf(types);
            instructions=instructions==null?"":instructions.strip();
        }
        static Configuration defaults(int pages) {
            return new Configuration(1,Math.max(1,pages),"중",EnumSet.allOf(QuizQuestion.Type.class),"");
        }
    }

    record GenerationRequest(Theme theme, Configuration configuration, int totalCount) {
        GenerationRequest {
            Objects.requireNonNull(theme);Objects.requireNonNull(configuration);
            if(totalCount<1||totalCount>120)throw new IllegalArgumentException("총 문제 수는 1–120개로 설정해 주세요.");
        }
    }

    static final List<String> LEVELS=List.of("중","중상","상","최상");
    private static final Color STUDIO_INK=new Color(0x191919),STUDIO_PAPER=Color.WHITE,
        STUDIO_LINE=MistWorkspaceTheme.LINE,STUDIO_RED=new Color(0xc93b36);
    final JButton settings=new JButton("상세 문제 설정");
    final JButton preview=new JButton("문제 화면 미리보기");
    final JButton generate=new CreateButton();
    final JButton workbookBack=QuizPlayDesign.button("← 문제집 목록",false);
    final Map<String,JButton> workbookButtons=new LinkedHashMap<>();
    final Map<String,JButton> workbookMenus=new LinkedHashMap<>();
    final JSpinner totalCount=new JSpinner(new SpinnerNumberModel(10,1,120,1));
    final JTextArea generationStatus=copy("개념 정리를 먼저 완료해 주세요.",12);
    final JTextArea generationReport=copy("",12);
    final JLabel state=new JLabel("문제집을 만들면 여기에 모여요.");
    final EnumMap<Theme,JToggleButton> themeButtons=new EnumMap<>(Theme.class);
    final List<QuizQuestionCard> cards=new ArrayList<>();
    final QuizRevealPanel detailsHost=new QuizRevealPanel();
    final QuizBookPreview bookPreview=new QuizBookPreview();
    final QuizModeSelector modeSelector;
    private final Column content=new Column();
    private final JPanel setupView=stack(),playView=stack(),workbookRows=stack();
    final QuizStudyView studyView=new QuizStudyView(workbookBack);
    private int questionFont=PdfWorkspace.displaySettings().quizFont();
    void setQuestionFont(int size) {
        int selected=Math.max(6,Math.min(64,size));
        if(questionFont==selected)return;
        questionFont=selected;studyView.refreshQuestion();revalidate();repaint();
    }
    private final QuizScrollPane scroll;
    private final JLayer<QuizScrollPane> completionLayer;
    private final QuizNavigationDock navigationDock;
    private final JPanel workbookScene=new JPanel(new BorderLayout());
    private final dev.synesis.poc.ui.LibrarySectionMotion workbookMotion=new dev.synesis.poc.ui.LibrarySectionMotion(workbookScene);
    private final JPanel emptyState;
    private final JTextArea description=copy("",13), settingsSummary=copy("",12);
    private final JTextArea workbookTitle=copy("",19), workbookMeta=copy("",12), workbookReport=copy("",12),workbookNote=copy("",12);
    private final JLabel workbookCount=label("문제집 목록",17,MistWorkspaceTheme.INK,Font.BOLD);
    private final JLabel previewNote=label("화면 예시 · PDF에서 생성한 문제가 아니에요.",12,MistWorkspaceTheme.MUTED,Font.PLAIN);
    private Configuration configuration=Configuration.defaults(0);
    private Theme selectedTheme=Theme.CONCEPT;
    private final javax.swing.Timer completionReset=new javax.swing.Timer(3000,event->resetCompletion());
    private final CompletionArrow completionArrow=new CompletionArrow();
    private int generationPercent;
    private int pages;
    private String documentId="";
    private long documentRevision, questionRevision;
    private boolean ready, tutorReady, previewActive, generationReady, generating, generationConnected;
    private Consumer<QuizTutorRequest> tutorRequest=ignored->{};
    private Runnable closeHandler=()->{};
    private Runnable maximizeHandler=()->{};
    private final JButton maximizeButton=dev.synesis.poc.ui.PanelCloseButtons.expand("N제 전체화면 · 다른 패널 접기",()->maximizeHandler.run());
    private Function<QuizQuestion,List<QuizConceptLinks.Target>> conceptLinks=ignored->List.of();
    private Consumer<QuizConceptLinks.Target> conceptNavigation=ignored->{};
    private Consumer<GenerationRequest> generationRequest=ignored->{};
    private final Map<String,QuizWorkbook> workbooks=new LinkedHashMap<>();
    private final Map<String,Map<String,QuizWorkbook.Answer>> workbookAnswers=new HashMap<>();
    private final Set<String> deletedWorkbooks=new HashSet<>();
    private QuizWorkbook currentWorkbook;
    private String requestedWorkbookId="";
    private Consumer<QuizWorkbook> workbookOpen=book->openWorkbook(book,Map.of());
    private BiConsumer<QuizWorkbook,Map<String,QuizWorkbook.Answer>> workbookProgress=(book,answers)->{};
    private BiConsumer<QuizWorkbook,String> workbookRename=(book,name)->renameWorkbook(book.id(),name);
    private Consumer<QuizWorkbook> workbookDelete=book->removeWorkbook(book.id());
    private GenerationRequest pendingGeneration;
    private boolean tutorConnected,workbookRowsDirty=true;
    Settings detailForm;

    QuizPanel() {
        super(new BorderLayout());
        setBackground(STUDIO_PAPER);
        completionReset.setRepeats(false);
        JPanel heading=MistWorkspaceTheme.heading(20);
        JLabel headingTitle=label("N제로 학습",18,MistWorkspaceTheme.INK,Font.BOLD);
        headingTitle.setIcon(MistWorkspaceTheme.icon("page-index",18));headingTitle.setIconTextGap(8);
        heading.add(headingTitle,BorderLayout.CENTER);
        JPanel headingActions=new JPanel(new FlowLayout(FlowLayout.RIGHT,2,0));headingActions.setOpaque(false);
        headingActions.add(maximizeButton);
        headingActions.add(dev.synesis.poc.ui.PanelCloseButtons.close("N제 창 닫기",()->closeHandler.run()));
        heading.add(headingActions,BorderLayout.EAST);
        add(heading,BorderLayout.NORTH);
        content.setBorder(new EmptyBorder(20,22,24,22));
        JPanel identity=stack();
        modeSelector=new QuizModeSelector(themeButtons,theme->{
            selectedTheme=theme;description.setText(theme.description);updateSummary();
        });
        identity.add(block(modeSelector));
        setupView.add(block(identity));
        setupView.add(Box.createVerticalStrut(30));
        JPanel cover=stack();
        cover.add(block(bookPreview));
        JPanel generation=stack();
        description.setText(selectedTheme.description);generation.add(description);
        generation.add(Box.createVerticalStrut(17));generation.add(settingsSummary);
        generation.add(Box.createVerticalStrut(14));
        styleSettingsToggle();settings.setHorizontalAlignment(SwingConstants.LEFT);
        settings.setPreferredSize(new Dimension(1,48));generation.add(block(settings));
        detailsHost.setOpaque(false);detailsHost.setBorder(new EmptyBorder(8,0,0,0));detailsHost.setVisible(false);generation.add(block(detailsHost));
        generation.add(Box.createVerticalStrut(18));
        JPanel countRow=new WrapRow(6,4);
        countRow.add(label("총 문제 수",13,STUDIO_INK,Font.BOLD));
        totalCount.setEditor(new JSpinner.NumberEditor(totalCount,"0"));
        JFormattedTextField countInput=((JSpinner.NumberEditor)totalCount.getEditor()).getTextField();
        countInput.setToolTipText("한번에 최대 120문제까지 만들 수 있어요.");
        if(countInput.getFormatter() instanceof javax.swing.text.NumberFormatter formatter)
            formatter.setCommitsOnValidEdit(true);
        javax.swing.text.AbstractDocument countDocument=(javax.swing.text.AbstractDocument)countInput.getDocument();
        javax.swing.text.DocumentFilter numberFilter=countDocument.getDocumentFilter();
        countDocument.setDocumentFilter(new javax.swing.text.DocumentFilter(){
            @Override public void insertString(FilterBypass fb,int offset,String text,javax.swing.text.AttributeSet attrs)
                    throws javax.swing.text.BadLocationException {replace(fb,offset,0,text,attrs);}
            @Override public void replace(FilterBypass fb,int offset,int length,String text,javax.swing.text.AttributeSet attrs)
                    throws javax.swing.text.BadLocationException {
                String before=fb.getDocument().getText(0,fb.getDocument().getLength());
                String candidate=before.substring(0,offset)+(text==null?"":text)+before.substring(offset+length);
                if(candidate.matches("[0-9]+") && new java.math.BigInteger(candidate).compareTo(java.math.BigInteger.valueOf(120))>0){
                    offset=0;length=before.length();text="120";
                }
                if(numberFilter!=null)numberFilter.replace(fb,offset,length,text,attrs);
                else fb.replace(offset,length,text,attrs);
            }
            @Override public void remove(FilterBypass fb,int offset,int length)throws javax.swing.text.BadLocationException {
                if(numberFilter!=null)numberFilter.remove(fb,offset,length);else fb.remove(offset,length);
            }
        });
        QuizSettingsStyle.spinner(totalCount,84);
        countRow.add(totalCount);countRow.add(label("개",12,MistWorkspaceTheme.TEXT,Font.PLAIN));
        generate.setEnabled(false);
        JPanel countBox=new StudyTheme.RoundedPanel(new BorderLayout(0,5),10,QuizSettingsStyle.SOFT,QuizSettingsStyle.LINE);
        countBox.setBorder(new EmptyBorder(9,12,11,12));countBox.add(countRow,BorderLayout.NORTH);
        countBox.add(copy("한번에 최대 120문제까지 만들 수 있어요.",11),BorderLayout.SOUTH);generation.add(block(countBox));
        generation.add(Box.createVerticalStrut(14));
        generation.add(block(generate));generation.add(Box.createVerticalStrut(12));
        generation.add(copy("배분·문제 생성에 사용한 크레딧이 차감돼요. 저장한 문제집은 추가 차감 없이 풀 수 있어요.",11));
        generation.add(Box.createVerticalStrut(8));
        generation.add(generationStatus);generation.add(Box.createVerticalStrut(8));
        generationReport.setVisible(false);generation.add(generationReport);
        generation.add(Box.createVerticalStrut(10));
        studioAction(preview);JPanel previewRow=new WrapRow(0,0);previewRow.add(preview);generation.add(block(previewRow));
        setupView.add(block(new BuilderArea(cover,generation)));
        setupView.add(Box.createVerticalStrut(28));
        setupView.add(block(rule(STUDIO_LINE)));setupView.add(Box.createVerticalStrut(20));
        setupView.add(workbookCount);setupView.add(Box.createVerticalStrut(12));
        setupView.add(copy("생성한 문제집을 골라 풀어보세요. 작성한 답과 풀이 상태가 저장돼요.",12));
        setupView.add(Box.createVerticalStrut(16));
        setupView.add(block(workbookRows));
        playView.add(block(studyView));
        emptyState=new StudyTheme.RoundedPanel(new BorderLayout(),8,Color.WHITE,STUDIO_LINE);
        emptyState.setBorder(new EmptyBorder(30,18,30,18));
        state.setFont(StudyTheme.font(Font.PLAIN,13));state.setForeground(MistWorkspaceTheme.MUTED);
        state.setHorizontalAlignment(SwingConstants.CENTER);
        emptyState.add(state);setupView.add(block(emptyState));
        content.add(block(setupView));content.add(block(playView));playView.setVisible(false);
        scroll=new QuizScrollPane(content,JScrollPane.VERTICAL_SCROLLBAR_AS_NEEDED,JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
        scroll.setBorder(null);scroll.getViewport().setBackground(STUDIO_PAPER);
        completionLayer=new JLayer<>(scroll,new javax.swing.plaf.LayerUI<QuizScrollPane>() {
            @Override public void paint(Graphics graphics,JComponent component) {
                super.paint(graphics,component);
                Graphics2D overlay=(Graphics2D)graphics.create();
                try {
                    Point origin=SwingUtilities.convertPoint(component,0,0,QuizPanel.this);
                    overlay.translate(-origin.x,-origin.y);completionArrow.paint(overlay);
                } finally {overlay.dispose();}
            }
        });
        navigationDock=new QuizNavigationDock(completionLayer,scroll,studyView.navigation,width->{
            Insets inset=content.getInsets();Rectangle bounds=studyView.navigationColumn(Math.max(1,width-inset.left-inset.right));
            bounds.x+=inset.left;return bounds;
        });
        workbookScene.setBackground(STUDIO_PAPER);workbookScene.add(navigationDock,BorderLayout.CENTER);
        add(workbookMotion.component(),BorderLayout.CENTER);
        settings.addActionListener(e->toggleSettings());
        preview.addActionListener(e->{if(previewActive)clearPreview();else showPreview();});
        generate.addActionListener(e->requestGeneration());
        totalCount.addChangeListener(e->updateBook(false));
        workbookBack.addActionListener(e->showWorkbookList());
        updateSummary();setReady(false);
    }

    // Local motion and settings validation must not re-layout the PDF and tutor beside this pane.
    @Override public boolean isValidateRoot(){return true;}

    private void updateThemeStyles() {
        modeSelector.select(selectedTheme,false);
    }

    Configuration configuration(){return configuration;}
    Theme selectedTheme(){return selectedTheme;}

    void reset(int count){reset(count,"");}
    void reset(int count,String id) {
        workbookMotion.cancel();
        completionReset.stop();completionArrow.stop();
        documentRevision++;pages=Math.max(0,count);documentId=id==null?"":id;
        configuration=Configuration.defaults(pages);
        selectedTheme=Theme.CONCEPT;themeButtons.get(selectedTheme).setSelected(true);updateThemeStyles();
        description.setText(selectedTheme.description);
        previewActive=false;generating=false;generationPercent=0;generationReady=false;pendingGeneration=null;
        currentWorkbook=null;requestedWorkbookId="";workbooks.clear();workbookAnswers.clear();deletedWorkbooks.clear();workbookButtons.clear();workbookMenus.clear();workbookRows.removeAll();workbookRowsDirty=true;
        generationStatus.setText("개념 정리를 먼저 완료해 주세요.");generationReport.setText("");generationReport.setVisible(false);
        totalCount.setValue(10);studyView.clear();cards.clear();previewNote.setVisible(false);
        emptyState.setVisible(true);state.setText("문제집을 만들면 여기에 모여요.");workbookCount.setText("문제집 목록");
        setupView.setVisible(true);playView.setVisible(false);navigationDock.setActive(false);
        preview.setText("문제 화면 미리보기");closeSettings();updateSummary();
        ready=false;tutorReady=false;setReady(false);
    }

    void setReady(boolean value) {
        ready=value&&pages>0;
        updateControls();
    }

    void setGenerationReady(boolean value) {
        generationReady=value;
        if(generationStatus.getText().equals("개념 정리를 먼저 완료해 주세요.")
            ||generationStatus.getText().equals("생성을 누르면 문제집을 만들고 아래 목록에 보관해요."))
            generationStatus.setText(value?"생성을 누르면 문제집을 만들고 아래 목록에 보관해요.":"개념 정리를 먼저 완료해 주세요.");
        updateControls();
    }

    void setGenerationRequestHandler(Consumer<GenerationRequest> handler) {
        generationRequest=Objects.requireNonNull(handler);generationConnected=true;updateControls();
    }

    void setGenerating(boolean value,String message) {
        if(value&&!generating) {
            completionReset.stop();completionArrow.stop();generationPercent=0;
        }
        if(!value&&generating&&generationPercent<100)generationPercent=0;
        generating=value;
        if(value) {
            String notice=(message==null||message.isBlank()?"문제를 생성하고 있어요.":message)+"\n평균 1분~5분 정도 걸려요. 진행률은 단계별 예상치예요.";
            if(!notice.equals(generationStatus.getText()))generationStatus.setText(notice);
            if(message!=null&&!message.isBlank())updateGenerationPercent(message);
        } else if(message!=null&&!message.isBlank())generationStatus.setText(message);
        updateControls();setTutorReady(tutorReady);revalidate();repaint();
    }

    void setGenerationProgress(int percent,String message) {
        setGenerating(true,message);
        generationPercent=Math.max(generationPercent,Math.max(0,Math.min(99,percent)));
        updateControls();
    }

    // Consume existing worker notifications only: no generation scheduling or transport changes.
    private void updateGenerationPercent(String message) {
        int next=0;
        if(message.contains("배분"))next=5;
        var completed=java.util.regex.Pattern.compile("완료\\s+(\\d+)/(\\d+)묶음").matcher(message);
        if(completed.find()) {
            double done=Double.parseDouble(completed.group(1)),total=Double.parseDouble(completed.group(2));
            if(total>0)next=10+(int)Math.round(75*Math.min(1,done/total));
        }
        if(message.contains("검토"))next=90;
        generationPercent=Math.max(generationPercent,Math.min(99,next));
    }

    private void updateControls() {
        boolean editable=ready&&!generating;
        settings.setEnabled(editable);preview.setEnabled(editable);totalCount.setEnabled(editable);
        themeButtons.values().forEach(button->button.setEnabled(editable));
        generate.setEnabled(editable&&generationReady&&generationConnected);
        generate.setText(generating?"문제집 생성 중 · "+generationPercent+"%"
            :generationPercent==100?"생성 완료 · 100%":"문제 생성하기");
        ((CreateButton)generate).setProgress(generating,generationPercent);
        generate.setToolTipText(generationReady?null:"개념 정리를 먼저 완료해 주세요.");
        if(detailForm!=null)Settings.enableTree(detailsHost,editable);
        workbookButtons.values().forEach(button->button.setEnabled(pages>0));
    }

    private void requestGeneration() {
        if(!generate.isEnabled()||generating)return;
        try {
            totalCount.commitEdit();
            Configuration snapshot=detailForm==null?configuration:detailForm.read();
            GenerationRequest request=new GenerationRequest(selectedTheme,snapshot,((Number)totalCount.getValue()).intValue());
            pendingGeneration=request;
            configuration=snapshot;closeSettings();updateSummary();
            if(previewActive)clearPreview();
            setGenerating(true,"전체 개념 목차로 출제 배분을 준비하고 있어요.");
            generationRequest.accept(request);
        } catch(java.text.ParseException|IllegalArgumentException invalid) {
            showGenerationFailure(invalid instanceof java.text.ParseException?"문제 수와 PDF 범위를 숫자로 입력해 주세요.":invalid.getMessage());
        } catch(RuntimeException failure) {
            showGenerationFailure("출제를 시작하지 못했어요. 다시 시도해 주세요.");
        }
    }

    void showGenerationResult(List<QuizQuestion> items,double elapsedSeconds,Double totalUsd,int requestedCount,String note) {
        if(!items.isEmpty()) {
            GenerationRequest setup=pendingGeneration==null?new GenerationRequest(selectedTheme,configuration,requestedCount):pendingGeneration;
            long now=System.currentTimeMillis();
            addWorkbook(new QuizWorkbook(UUID.randomUUID().toString(),documentId,setup.theme().title+" 문제집 · "+date(now),
                setup.theme(),setup.configuration().difficulty(),requestedCount,now,elapsedSeconds,totalUsd,note,items));
            return;
        }
        generationReport.setText(report(0,requestedCount,elapsedSeconds,totalUsd));generationReport.setVisible(true);
        showWorkbookList();
        String message="이번에는 문제집을 만들지 못했어요. 출제 범위와 안내를 확인해 주세요.";
        if(note!=null&&!note.isBlank())message+="\n"+note.strip();
        if(!workbooks.isEmpty())message+="\n이전에 만든 문제집은 유지했어요.";
        pendingGeneration=null;setGenerating(false,message);
    }

    private static String report(int actual,int requestedCount,double elapsedSeconds,Double totalUsd) {
        StringBuilder report=new StringBuilder("생성 ").append(actual).append(" / ").append(requestedCount)
            .append("문제 · 총 시간 ").append(duration(elapsedSeconds));
        if(totalUsd!=null&&Double.isFinite(totalUsd)&&totalUsd>=0) {
            BigDecimal credits=CreditWallet.credits(totalUsd);
            report.append("\n총 사용 ").append(CreditWallet.display(credits)).append(" 크레딧");
            if(actual>0)report.append("\n문제당 ").append(CreditWallet.display(credits.divide(BigDecimal.valueOf(actual),20,RoundingMode.HALF_UP))).append(" 크레딧");
            report.append("\n배분·생성 비용 포함");
        } else report.append("\n사용 크레딧 확인 대기 · 확인되지 않은 요청은 예약 크레딧으로 유지돼요.");
        return report.toString();
    }

    void showGenerationFailure(String message) {
        completionReset.stop();completionArrow.stop();generationPercent=0;
        String explanation=message==null||message.isBlank()?"문제 출제를 완료하지 못했어요.":message.strip();
        if(!workbooks.isEmpty())explanation+="\n이전에 만든 문제집은 유지했어요.";
        pendingGeneration=null;
        setGenerating(false,explanation);
    }

    void setWorkbooks(List<QuizWorkbook> items) {
        for(QuizWorkbook book:items)validateWorkbook(book);
        captureProgress();workbooks.clear();
        for(QuizWorkbook book:items)workbooks.put(book.id(),book);
        workbookRowsDirty=true;
        workbookAnswers.keySet().retainAll(workbooks.keySet());
        currentWorkbook=null;
        showWorkbookList();
    }

    void acceptGenerationSnapshot(QuizWorkbook book) {
        if(!generating||deletedWorkbooks.contains(book.id()))return;
        validateWorkbook(book);
        workbooks.put(book.id(),book);workbookRowsDirty=true;
        if(currentWorkbook!=null&&currentWorkbook.id().equals(book.id()))updateOpenWorkbook(book);
        else if(currentWorkbook==null)renderWorkbookRows();
    }

    private void updateOpenWorkbook(QuizWorkbook book) {
        captureProgress();
        currentWorkbook=book;
        workbookMeta.setText(book.theme().title+" · "+book.levelDescription()+" · "+book.questions().size()+"/"+book.requestedCount()+"문제"
            +(generating?" · 나머지 생성 중":""));
        workbookReport.setText(report(book.questions().size(),book.requestedCount(),book.elapsedSeconds(),book.totalUsd()));
        workbookNote.setText(book.note());workbookNote.setVisible(!book.note().isBlank());
        studyView.update(book.questions());updatePlayHeading();
        workbookAnswers.put(book.id(),snapshotAnswers());
        content.revalidate();content.repaint();
    }

    void addWorkbook(QuizWorkbook book) {
        if(deletedWorkbooks.contains(book.id()))return;
        validateWorkbook(book);workbooks.put(book.id(),book);workbookRowsDirty=true;
        generationReport.setText(report(book.questions().size(),book.requestedCount(),book.elapsedSeconds(),book.totalUsd()));
        generationReport.setVisible(true);pendingGeneration=null;
        if(currentWorkbook!=null) {
            if(currentWorkbook.id().equals(book.id()))updateOpenWorkbook(book);
        } else showWorkbookList();
        String message=book.questions().size()==book.requestedCount()?"문제집을 만들었어요. 아래 목록에서 선택해 풀어보세요."
            :"완성된 문제로 문제집을 만들었어요. 아래 목록에서 선택해 풀어보세요.";
        if(book.note()!=null&&!book.note().isBlank())message+="\n"+book.note().strip();
        generationPercent=100;
        setGenerating(false,message);
        completionReset.restart();
        long revision=documentRevision;
        SwingUtilities.invokeLater(()->{
            if(documentRevision==revision&&generationPercent==100&&!generating)completionArrow.start();
        });
        if(currentWorkbook!=null&&currentWorkbook.id().equals(book.id())) {
            workbookMeta.setText(book.theme().title+" · "+book.levelDescription()+" · "+book.questions().size()+"문제");
            updatePlayHeading();
        }
    }

    private void resetCompletion() {
        completionReset.stop();completionArrow.stop();
        if(!generating&&generationPercent==100){generationPercent=0;updateControls();}
    }

    @Override public void removeNotify() {
        workbookMotion.cancel();
        completionReset.stop();completionArrow.stop();
        if(generationPercent==100){generationPercent=0;updateControls();}
        super.removeNotify();
    }

    static Point[] completionPath(Rectangle clip,Rectangle button,Rectangle list) {
        if(clip.width<64||clip.height<96||button.width<=0||button.height<=0)return null;
        int left=clip.x+20,right=clip.x+clip.width-20,bottom=clip.y+clip.height-18;
        int travel=Math.min(96,clip.height/2);
        Point from=new Point(Math.max(left,Math.min(right,button.x+button.width-34)),
            Math.max(clip.y+18,Math.min(bottom-travel,button.y+button.height/2)));
        Point to=new Point(Math.max(left,Math.min(right,list.x+Math.min(100,list.width/2))),
            Math.min(bottom,Math.max(from.y+travel,list.y+list.height/2)));
        return new Point[]{from,to};
    }

    /** One small painted arrow, without component snapshots or per-frame layout. */
    private final class CompletionArrow {
        private final javax.swing.Timer timer=new javax.swing.Timer(16,event->advance());
        private Point from,to;
        private Rectangle clip,damage;
        private long started,requested;
        private double progress;
        void start() {
            stop();
            if(Boolean.getBoolean("synesis.reduceMotion"))return;
            requested=System.nanoTime();timer.setCoalesce(true);timer.start();advance();
        }
        private boolean preparePath() {
            if(!isShowing()||!generate.isShowing()||!setupView.isVisible())return false;
            clip=SwingUtilities.convertRectangle(scroll.getViewport(),
                new Rectangle(0,0,scroll.getViewport().getWidth(),scroll.getViewport().getHeight()),QuizPanel.this);
            Rectangle button=SwingUtilities.convertRectangle(generate,new Rectangle(0,0,generate.getWidth(),generate.getHeight()),QuizPanel.this);
            Rectangle list=SwingUtilities.convertRectangle(workbookCount,new Rectangle(0,0,workbookCount.getWidth(),workbookCount.getHeight()),QuizPanel.this);
            Point[] path=completionPath(clip,button,list);
            if(path==null)return false;
            from=path[0];to=path[1];started=System.nanoTime();progress=0;return true;
        }
        private Point point(double t) {
            double u=1-t,cx=from.x+32,cy=to.y-24;
            return new Point((int)Math.round(u*u*from.x+2*u*t*cx+t*t*to.x),
                (int)Math.round(u*u*from.y+2*u*t*cy+t*t*to.y));
        }
        private void advance() {
            if(from==null) {
                // A tab/panel may still be revealing its children after completion.
                if(!preparePath()) {if(System.nanoTime()-requested>800_000_000L)stop();return;}
            }
            if(!isShowing()||!setupView.isVisible()){stop();return;}
            double time=Math.min(1,(System.nanoTime()-started)/700_000_000d);
            progress=time*time*(3-2*time);
            Point at=point(progress);
            Rectangle next=new Rectangle(at.x-36,at.y-36,72,72);
            Rectangle dirty=damage==null?next:damage.union(next);damage=next;
            repaintOverlay(dirty);
            if(time>=1)stop();
        }
        void stop() {
            timer.stop();from=to=null;
            if(damage!=null){repaintOverlay(damage);damage=null;}
        }
        private void repaintOverlay(Rectangle dirty) {
            if(completionLayer==null)return;
            Rectangle local=SwingUtilities.convertRectangle(QuizPanel.this,dirty,completionLayer);
            // JLayer is a painting origin: even dirty child repaints include the overlay.
            completionLayer.repaint(local.x,local.y,local.width,local.height);
        }
        void paint(Graphics graphics) {
            if(from==null||!timer.isRunning())return;
            Graphics2D g=(Graphics2D)graphics.create();
            try {
                g.clip(clip);g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                float alpha=(float)Math.min(1,(1-progress)/.18);
                g.setComposite(AlphaComposite.SrcOver.derive(alpha));
                Point at=point(progress),before=point(Math.max(0,progress-.025));
                double angle=Math.atan2(at.y-before.y,at.x-before.x);
                g.translate(at.x,at.y);g.rotate(angle);
                g.setColor(progress<.06?Color.WHITE:STUDIO_RED);
                g.setStroke(new BasicStroke(2.5f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                g.drawLine(-24,0,3,0);g.drawLine(-5,-7,3,0);g.drawLine(-5,7,3,0);
            } finally {g.dispose();}
        }
    }

    private void validateWorkbook(QuizWorkbook book) {
        Objects.requireNonNull(book);
        if(!documentId.equals(book.documentId()))throw new IllegalArgumentException("현재 PDF와 다른 문제집이에요.");
    }

    List<QuizWorkbook> workbooks() {
        return workbooks.values().stream().sorted(Comparator.comparingLong(QuizWorkbook::createdAtMs).reversed()
            .thenComparing(QuizWorkbook::id)).toList();
    }

    void setWorkbookOpenHandler(Consumer<QuizWorkbook> handler) {workbookOpen=Objects.requireNonNull(handler);}
    void setWorkbookProgressHandler(BiConsumer<QuizWorkbook,Map<String,QuizWorkbook.Answer>> handler) {
        workbookProgress=Objects.requireNonNull(handler);
    }
    void setWorkbookManagementHandlers(BiConsumer<QuizWorkbook,String> rename,Consumer<QuizWorkbook> delete) {
        workbookRename=Objects.requireNonNull(rename);workbookDelete=Objects.requireNonNull(delete);
    }
    void renameWorkbook(String id,String name) {
        QuizWorkbook existing=workbooks.get(id);if(existing==null)return;
        QuizWorkbook renamed=existing.withTitle(QuizWorkbookStore.validTitle(name));workbooks.put(id,renamed);
        if(currentWorkbook!=null&&currentWorkbook.id().equals(id)){currentWorkbook=renamed;workbookTitle.setText(renamed.title());updatePlayHeading();}
        workbookRowsDirty=true;if(setupView.isVisible())renderWorkbookRows();content.revalidate();content.repaint();
    }
    void removeWorkbook(String id) {
        if(!workbooks.containsKey(id))return;
        deletedWorkbooks.add(id);workbooks.remove(id);workbookAnswers.remove(id);workbookRowsDirty=true;
        if(requestedWorkbookId.equals(id))requestedWorkbookId="";
        if(currentWorkbook!=null&&currentWorkbook.id().equals(id)){currentWorkbook=null;showWorkbookList();}
        else {renderWorkbookRows();content.revalidate();content.repaint();}
    }
    String currentWorkbookId(){return currentWorkbook==null?"":currentWorkbook.id();}
    String requestedWorkbookId(){return requestedWorkbookId;}

    void openWorkbook(QuizWorkbook book,Map<String,QuizWorkbook.Answer> savedAnswers) {
        if(!documentId.equals(book.documentId())||!requestedWorkbookId.equals(book.id())||!workbooks.containsKey(book.id()))return;
        long revision=documentRevision;
        workbookMotion.change(()->{
            if(revision==documentRevision)openWorkbookNow(book,savedAnswers);
        },false);
    }

    private void openWorkbookNow(QuizWorkbook book,Map<String,QuizWorkbook.Answer> savedAnswers) {
        if(!documentId.equals(book.documentId())||!requestedWorkbookId.equals(book.id())||!workbooks.containsKey(book.id()))return;
        book=workbooks.get(book.id());
        captureProgress();currentWorkbook=book;previewActive=false;previewNote.setVisible(false);
        preview.setText("문제 화면 미리보기");
        workbookTitle.setText(book.title());
        workbookMeta.setText(book.theme().title+" · "+book.levelDescription()+" · "+book.questions().size()+"문제\n생성 "+date(book.createdAtMs()));
        workbookReport.setText(report(book.questions().size(),book.requestedCount(),book.elapsedSeconds(),book.totalUsd()));
        workbookReport.setVisible(true);workbookNote.setText(book.note()==null?"":book.note());
        workbookNote.setVisible(!workbookNote.getText().isBlank());
        Map<String,QuizWorkbook.Answer> answers=workbookAnswers.getOrDefault(book.id(),savedAnswers==null?Map.of():savedAnswers);
        renderQuestions(book.questions(),answers);
        workbookAnswers.put(book.id(),snapshotAnswers());
        setupView.setVisible(false);playView.setVisible(true);refreshView();
    }

    void showWorkbookList() {
        if(!playView.isVisible()&&!workbookMotion.active()){showWorkbookListNow();return;}
        long revision=documentRevision;
        workbookMotion.change(()->{
            if(revision==documentRevision)showWorkbookListNow();
        },false);
    }

    private void showWorkbookListNow() {
        captureProgress();currentWorkbook=null;requestedWorkbookId="";previewActive=false;
        questionRevision++;studyView.clear();cards.clear();previewNote.setVisible(false);preview.setText("문제 화면 미리보기");
        renderWorkbookRows();setupView.setVisible(true);playView.setVisible(false);refreshView();
    }

    private void renderWorkbookRows() {
        if(!workbookRowsDirty){updateControls();return;}
        workbookRows.removeAll();workbookButtons.clear();workbookMenus.clear();
        workbookCount.setText(workbooks.isEmpty()?"문제집 목록":"문제집 목록 · "+workbooks.size()+"개");
        for(QuizWorkbook book:workbooks()) {
            JPanel row=new StudyTheme.RoundedPanel(new BorderLayout(0,12),8,Color.WHITE,STUDIO_LINE);
            row.setBorder(new EmptyBorder(16,16,16,16));
            JPanel description=stack();JTextArea title=copy(book.title(),14);
            title.setFont(StudyTheme.font(Font.BOLD,14));title.setForeground(MistWorkspaceTheme.INK);
            JButton menu=new JButton("⋯");MistWorkspaceTheme.button(menu,true);menu.setFont(StudyTheme.font(Font.BOLD,18));
            menu.setBorder(new EmptyBorder(0,0,0,0));menu.setPreferredSize(new Dimension(30,28));
            menu.setToolTipText("문제집 메뉴");menu.getAccessibleContext().setAccessibleName(book.title()+" 메뉴");
            JPopupMenu actions=new JPopupMenu();JMenuItem rename=new JMenuItem("이름 변경"),delete=new JMenuItem("문제집 삭제");
            rename.addActionListener(e->requestWorkbookRename(book.id()));delete.addActionListener(e->requestWorkbookDelete(book.id()));
            actions.add(rename);actions.add(delete);menu.setComponentPopupMenu(actions);menu.addActionListener(e->actions.show(menu,0,menu.getHeight()));
            workbookMenus.put(book.id(),menu);
            JPanel titleRow=new JPanel(new BorderLayout(8,0));titleRow.setOpaque(false);titleRow.add(title);
            JPanel menuSlot=new JPanel(new BorderLayout());menuSlot.setOpaque(false);menuSlot.add(menu,BorderLayout.NORTH);titleRow.add(menuSlot,BorderLayout.EAST);description.add(block(titleRow));
            description.add(Box.createVerticalStrut(7));
            description.add(copy(book.theme().title+" · "+book.levelDescription()+" · "+book.questions().size()+"문제\n"+date(book.createdAtMs()),12));
            description.add(Box.createVerticalStrut(6));
            String cost=book.totalUsd()==null?"사용 크레딧 확인 대기":"사용 "+CreditWallet.display(CreditWallet.credits(book.totalUsd()))+" 크레딧";
            description.add(copy("생성 시간 "+duration(book.elapsedSeconds())+" · "+cost,12));
            JLabel cover=new JLabel(new WorkbookCoverIcon(book.theme()));cover.setVerticalAlignment(SwingConstants.TOP);
            JPanel spread=new JPanel(new BorderLayout(16,0));spread.setOpaque(false);spread.add(cover,BorderLayout.WEST);spread.add(description);
            row.add(spread,BorderLayout.CENTER);
            JButton open=new JButton("문제집 풀기  →");studioAction(open);open.getAccessibleContext().setAccessibleName(book.title()+" 열기");
            open.addActionListener(event->{
                if(!documentId.equals(book.documentId())||!workbooks.containsKey(book.id()))return;
                captureProgress();requestedWorkbookId=book.id();workbookOpen.accept(workbooks.get(book.id()));
            });
            row.add(open,BorderLayout.SOUTH);workbookButtons.put(book.id(),open);
            java.awt.event.MouseAdapter click=new java.awt.event.MouseAdapter(){
                @Override public void mouseClicked(java.awt.event.MouseEvent event){if(SwingUtilities.isLeftMouseButton(event)&&event.getClickCount()==1)open.doClick();}
            };
            clickable(row,open,click);workbookRows.add(block(row));workbookRows.add(Box.createVerticalStrut(12));
        }
        workbookRowsDirty=false;emptyState.setVisible(workbooks.isEmpty());updateControls();
    }

    private static void clickable(Component component,JButton open,java.awt.event.MouseAdapter click) {
        if(component instanceof AbstractButton)return;
        component.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));component.addMouseListener(click);
        if(component instanceof Container parent)for(Component child:parent.getComponents())clickable(child,open,click);
    }

    private void requestWorkbookRename(String id) {
        QuizWorkbook book=workbooks.get(id);if(book==null)return;
        String value=(String)JOptionPane.showInputDialog(this,"새 문제집 이름을 입력해 주세요.","문제집 이름 변경",JOptionPane.PLAIN_MESSAGE,null,null,book.title());
        if(value==null)return;
        try {workbookRename.accept(book,QuizWorkbookStore.validTitle(value));}
        catch(IllegalArgumentException invalid){JOptionPane.showMessageDialog(this,invalid.getMessage(),"문제집 이름 변경",JOptionPane.WARNING_MESSAGE);}
    }
    private void requestWorkbookDelete(String id) {
        QuizWorkbook book=workbooks.get(id);if(book==null)return;
        int choice=JOptionPane.showOptionDialog(this,"‘"+book.title()+"’ 문제집을 삭제할까요?\nPDF와 다른 문제집은 유지돼요.","문제집 삭제",JOptionPane.OK_CANCEL_OPTION,JOptionPane.WARNING_MESSAGE,null,new Object[]{"삭제","취소"},"취소");
        if(choice==0)workbookDelete.accept(book);
    }

    private Map<String,QuizWorkbook.Answer> snapshotAnswers() {return studyView.snapshot();}
    private void captureProgress() {
        if(currentWorkbook==null||previewActive)return;
        Map<String,QuizWorkbook.Answer> answers=snapshotAnswers();
        workbookAnswers.put(currentWorkbook.id(),answers);workbookProgress.accept(currentWorkbook,answers);
    }
    void scrollToTop() {
        // Apply after the tab transition's final layout, before its return snapshot.
        if(LayoutMotionPanel.defer(this,"quiz-tab-scroll-top",this::scrollToTop))return;
        scroll.scrollToTop();
    }
    private void updatePlayHeading(){
        studyView.heading(workbookTitle.getText(),workbookMeta.getText(),previewActive?previewNote.getText():workbookNote.isVisible()?workbookNote.getText():"");
        studyView.setToolTipText(workbookReport.isVisible()?workbookReport.getText():null);
    }
    private void refreshView(){
        navigationDock.setActive(playView.isVisible());
        Color background=playView.isVisible()?QuizPlayDesign.PAGE:STUDIO_PAPER;
        content.setBackground(background);scroll.getViewport().setBackground(background);
        updatePlayHeading();content.revalidate();content.repaint();scroll.scrollToTop();revalidate();repaint();
    }
    private static String date(long milliseconds) {
        return DateTimeFormatter.ofPattern("yyyy.MM.dd HH:mm").withZone(ZoneId.of("Asia/Seoul")).format(Instant.ofEpochMilli(milliseconds));
    }
    private static String duration(double seconds) {
        return seconds<60?String.format(Locale.ROOT,"%.1f초",Math.max(0,seconds))
            :String.format(Locale.ROOT,"%d분 %.0f초",(int)(seconds/60),seconds%60);
    }

    void setTutorReady(boolean value) {
        tutorReady=value;
        for(QuizQuestionCard card:cards)card.tutorButton.setEnabled(value&&tutorConnected&&!generating);
    }

    void setTutorRequestHandler(Consumer<QuizTutorRequest> handler) {
        tutorRequest=Objects.requireNonNull(handler);tutorConnected=true;
        setTutorReady(tutorReady);
    }

    void setConceptNavigation(Function<QuizQuestion,List<QuizConceptLinks.Target>> links,
                              Consumer<QuizConceptLinks.Target> handler) {
        conceptLinks=Objects.requireNonNull(links);conceptNavigation=Objects.requireNonNull(handler);
    }

    void setCloseHandler(Runnable handler){closeHandler=Objects.requireNonNull(handler);}
    void setViewSelector(JButton selector){
        JPanel heading=(JPanel)((BorderLayout)getLayout()).getLayoutComponent(BorderLayout.NORTH);
        Component old=((BorderLayout)heading.getLayout()).getLayoutComponent(BorderLayout.CENTER);
        heading.remove(old);heading.add(selector,BorderLayout.CENTER);
    }
    void setMaximizeHandler(Runnable handler){maximizeHandler=Objects.requireNonNull(handler);}
    void setMaximizeAction(String label){
        maximizeButton.setToolTipText(label);maximizeButton.getAccessibleContext().setAccessibleName(label);
    }

    private void updateSummary() {
        String types=Arrays.stream(QuizQuestion.Type.values()).filter(configuration.types()::contains)
            .map(QuizPanel::typeTitle).reduce((a,b)->a+" · "+b).orElse("");
        settingsSummary.setText(selectedTheme.profileTargetDescription()+"  ·  "+types
            +(pages>0?"\nPDF "+configuration.start()+"–"+configuration.end()+"쪽":""));
        updateBook(true);
        revalidate();repaint();
    }

    private void updateBook(boolean animate) {
        bookPreview.setSelection(selectedTheme,configuration.difficulty(),((Number)totalCount.getValue()).intValue(),animate);
    }

    private void toggleSettings() {
        if(detailsHost.isExpanded()){closeSettings();return;}
        detailForm=new Settings(pages,configuration);
        Settings form=detailForm;
        JPanel frame=new StudyTheme.RoundedPanel(new BorderLayout(0,18),12,QuizSettingsStyle.SOFT,QuizSettingsStyle.LINE);
        frame.setBorder(new EmptyBorder(18,18,16,18));
        frame.add(detailForm,BorderLayout.CENTER);
        JPanel footer=new JPanel(new BorderLayout(8,8));footer.setOpaque(false);
        footer.setBorder(BorderFactory.createCompoundBorder(BorderFactory.createMatteBorder(1,0,0,0,QuizSettingsStyle.LINE),new EmptyBorder(12,0,0,0)));
        JLabel error=label("",12,new Color(0xa83d3d),Font.PLAIN);
        JPanel buttons=new JPanel(new FlowLayout(FlowLayout.RIGHT,6,0));buttons.setOpaque(false);
        JButton cancel=new JButton("닫기"),apply=new JButton("설정 적용");
        QuizSettingsStyle.button(cancel,false);QuizSettingsStyle.button(apply,true);
        buttons.add(cancel);buttons.add(apply);footer.add(error,BorderLayout.NORTH);footer.add(buttons,BorderLayout.SOUTH);
        frame.add(footer,BorderLayout.SOUTH);
        cancel.addActionListener(e->{if(detailForm==form&&detailsHost.isExpanded())closeSettings();});
        apply.addActionListener(e->{
            if(detailForm!=form||!detailsHost.isExpanded())return;
            try {
                configuration=form.read();closeSettings();updateSummary();
                if(previewActive)showPreview();
            } catch(java.text.ParseException|IllegalArgumentException invalid) {
                error.setText(invalid instanceof java.text.ParseException?"올바른 페이지 번호를 입력해 주세요.":invalid.getMessage());
            }
        });
        detailsHost.removeAll();detailsHost.add(frame);detailsHost.setExpanded(true,true);
        settings.repaint();
        revalidate();repaint();
    }

    private void closeSettings() {
        Settings.enableTree(detailsHost,false);
        detailForm=null;
        detailsHost.setExpanded(false,true,()->{if(detailForm==null)detailsHost.removeAll();});
        settings.setText("상세 문제 설정");revalidate();repaint();
    }

    void showQuestions(List<QuizQuestion> items) {
        workbookMotion.cancel();
        captureProgress();currentWorkbook=null;requestedWorkbookId="";
        workbookTitle.setText("문제 풀기");workbookMeta.setText("");workbookReport.setVisible(false);workbookNote.setVisible(false);
        renderQuestions(items);setupView.setVisible(false);playView.setVisible(true);refreshView();
    }

    private void renderQuestions(List<QuizQuestion> items) {renderQuestions(items,Map.of());}

    private void renderQuestions(List<QuizQuestion> items,Map<String,QuizWorkbook.Answer> answers) {
        for(QuizQuestion item:items)
            if(!item.preview()&&!Objects.equals(documentId,item.documentId()))
                throw new IllegalArgumentException("현재 PDF와 다른 문제예요.");
        long expectedRevision=documentRevision,expectedQuestions=++questionRevision;
        studyView.configure((item,number)->{
            QuizQuestionCard[] reference=new QuizQuestionCard[1];
            QuizQuestionCard card=new QuizQuestionCard(item,number,request->{
                if(expectedRevision==documentRevision&&expectedQuestions==questionRevision&&cards.contains(reference[0])&&tutorReady&&tutorConnected&&!generating)tutorRequest.accept(request);
            },true,questionFont);
            reference[0]=card;
            card.setConceptNavigation(()->conceptLinks.apply(item),target->{
                if(expectedRevision==documentRevision&&expectedQuestions==questionRevision&&cards.contains(card)&&!previewActive)conceptNavigation.accept(target);
            });
            card.tutorButton.setEnabled(tutorReady&&tutorConnected&&!generating);return card;
        },card->{cards.clear();if(card!=null)cards.add(card);},()->{
            if(expectedRevision==documentRevision&&expectedQuestions==questionRevision&&currentWorkbook!=null&&!previewActive)captureProgress();
        },this::scrollToTop);
        studyView.open(items,answers,previewActive);updatePlayHeading();revalidate();repaint();
    }

    void showPreview() {
        if(generating)return;
        workbookMotion.cancel();
        captureProgress();currentWorkbook=null;requestedWorkbookId="";
        previewActive=true;preview.setText("미리보기 닫기");previewNote.setVisible(true);
        workbookTitle.setText("문제 화면 미리보기");workbookMeta.setText("선택한 문제 형식의 화면 예시예요.");workbookReport.setVisible(false);workbookNote.setVisible(false);
        List<QuizQuestion> examples=List.of(
            new QuizQuestion("preview-ox",documentId,QuizQuestion.Type.OX,"도형의 성질",
                "정사각형은 네 변의 길이가 모두 같아요.",List.of(),"O",
                "정사각형은 네 변의 길이가 같고 네 각이 모두 직각인 사각형이에요.",List.of(),List.of(),true),
            new QuizQuestion("preview-mcq",documentId,QuizQuestion.Type.MCQ,"직사각형의 넓이",
                "가로가 3 cm, 세로가 4 cm인 직사각형의 넓이는 얼마인가요?",
                List.of(new QuizQuestion.Option("A","7 cm²","두 길이를 더한 값이에요."),
                    new QuizQuestion.Option("B","12 cm²","가로와 세로를 곱한 값이에요."),
                    new QuizQuestion.Option("C","14 cm²","둘레를 계산한 값이에요."),
                    new QuizQuestion.Option("D","24 cm²","넓이를 두 배로 계산한 값이에요.")),
                "B","직사각형의 넓이는 가로 × 세로이므로 3 × 4 = 12 cm²예요.",List.of(),List.of(),true),
            new QuizQuestion("preview-word",documentId,QuizQuestion.Type.SHORT_ANSWER,"도형의 성질",
                "네 변의 길이가 모두 같고 네 각이 직각인 사각형의 이름을 적어보세요.",
                List.of(),"정사각형","모범답안과 내가 쓴 용어를 비교해보세요.",List.of(),List.of(),true),
            new QuizQuestion("preview-essay",documentId,QuizQuestion.Type.ESSAY,"직사각형의 넓이",
                "직사각형의 가로가 두 배가 되고 세로는 그대로일 때, 넓이가 어떻게 변하는지 이유와 함께 설명해보세요.",
                List.of(),"넓이는 가로 × 세로예요. 세로가 같고 가로만 두 배가 되면 넓이도 두 배가 돼요.",
                "답안의 문장보다 포함한 핵심 내용을 비교해보세요.",
                List.of("넓이는 가로와 세로의 곱이에요.","세로는 같고 가로만 두 배이므로 넓이도 두 배예요."),List.of(),true));
        renderQuestions(examples.stream().filter(q->configuration.types().contains(q.type())).toList());
        setupView.setVisible(false);playView.setVisible(true);refreshView();
    }

    private void clearPreview() {
        showWorkbookList();
    }

    static String typeTitle(QuizQuestion.Type type) {
        return type.label();
    }

    static final class Settings extends JPanel {
        final JSpinner from,to;
        final JComboBox<String> level=new JComboBox<>(LEVELS.toArray(String[]::new));
        final JTextArea extra=new JTextArea(3,18){
            @Override protected void paintComponent(Graphics graphics){
                super.paintComponent(graphics);
                if(getText().isEmpty()){
                    Graphics2D g=(Graphics2D)graphics.create();
                    try {
                        g.setFont(getFont());g.setColor(new Color(0x989fa9));
                        g.drawString("예: 개념 비교 위주로 출제해 주세요.",getInsets().left,getInsets().top+g.getFontMetrics().getAscent());
                    }finally{g.dispose();}
                }
            }
        };
        final EnumMap<QuizQuestion.Type,JCheckBox> formats=new EnumMap<>(QuizQuestion.Type.class);
        Settings(int pages,int start,int end,String difficulty,String instructions) {
            this(pages,new Configuration(start,end,difficulty,EnumSet.allOf(QuizQuestion.Type.class),instructions));
        }
        Settings(int pages,Configuration value) {
            super(new GridBagLayout());setOpaque(false);
            from=new JSpinner(new SpinnerNumberModel(value.start(),1,Math.max(1,pages),1));
            to=new JSpinner(new SpinnerNumberModel(value.end(),1,Math.max(1,pages),1));
            int y=0;
            row(copy("모든 학습 테마에 공통으로 적용돼요.",11),y++);
            JPanel difficulty=new JPanel(new BorderLayout(12,0));difficulty.setOpaque(false);
            difficulty.add(label("난이도",13,QuizSettingsStyle.INK,Font.BOLD),BorderLayout.WEST);
            MistWorkspaceTheme.comboBox(level,true);level.setPreferredSize(new Dimension(112,36));
            level.setBackground(Color.WHITE);level.setBorder(new dev.synesis.poc.ui.LibraryDesign.RoundedBorder(8,QuizSettingsStyle.LINE,new Insets(4,9,4,6)));
            level.setSelectedItem(value.difficulty());difficulty.add(level,BorderLayout.EAST); // Legacy value is retained; new runs use book-level profiles.
            row(rule(QuizSettingsStyle.LINE),y++);
            row(label("포함할 문제 형식",13,QuizSettingsStyle.INK,Font.BOLD),y++);
            JPanel formatChoices=new JPanel(new GridLayout(0,2,8,8));formatChoices.setOpaque(false);
            for(QuizQuestion.Type type:List.of(QuizQuestion.Type.OX,QuizQuestion.Type.SHORT_ANSWER,QuizQuestion.Type.MCQ,QuizQuestion.Type.ESSAY)) {
                JCheckBox box=new JCheckBox(typeTitle(type),value.types().contains(type));
                QuizSettingsStyle.format(box);
                box.putClientProperty("synesis.preserveFont",true);formats.put(type,box);formatChoices.add(box);
            }
            row(formatChoices,y++);
            row(copy("서답형·서술형은 모범답안과 직접 비교해요.",11),y++);
            row(rule(QuizSettingsStyle.LINE),y++);
            row(label("PDF 범위",13,QuizSettingsStyle.INK,Font.BOLD),y++);
            JPanel range=new WrapRow(6,0);
            QuizSettingsStyle.spinner(from,84);QuizSettingsStyle.spinner(to,84);
            range.add(from);range.add(label("—",12,QuizSettingsStyle.MUTED,Font.PLAIN));range.add(to);
            JButton all=new JButton("전체");QuizSettingsStyle.button(all,false);all.addActionListener(e->{from.setValue(1);to.setValue(Math.max(1,pages));});range.add(all);
            from.getAccessibleContext().setAccessibleName("PDF 시작 페이지");to.getAccessibleContext().setAccessibleName("PDF 마지막 페이지");
            row(range,y++);
            row(label("추가 요청 · 선택",13,QuizSettingsStyle.INK,Font.BOLD),y++);
            extra.setLineWrap(true);extra.setWrapStyleWord(true);extra.setText(value.instructions());extra.setFont(StudyTheme.font(Font.PLAIN,12));
            extra.setForeground(QuizSettingsStyle.INK);extra.setBackground(Color.WHITE);extra.setBorder(new EmptyBorder(12,12,12,12));
            extra.getAccessibleContext().setAccessibleName("추가 출제 요청");
            JScrollPane extraScroll=new QuizScrollPane(extra,JScrollPane.VERTICAL_SCROLLBAR_AS_NEEDED,JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
            extraScroll.setBorder(new dev.synesis.poc.ui.LibraryDesign.RoundedBorder(8,QuizSettingsStyle.LINE,new Insets(1,1,1,1)));
            row(extraScroll,y);
        }
        private void row(Component component,int index) {
            GridBagConstraints c=new GridBagConstraints();c.gridx=0;c.gridy=index;c.weightx=1;c.fill=GridBagConstraints.HORIZONTAL;
            c.anchor=GridBagConstraints.NORTHWEST;c.insets=new Insets(index==0?0:12,0,0,0);add(component,c);
        }
        Configuration read()throws java.text.ParseException {
            from.commitEdit();to.commitEdit();
            Set<QuizQuestion.Type> selected=EnumSet.noneOf(QuizQuestion.Type.class);
            formats.forEach((type,box)->{if(box.isSelected())selected.add(type);});
            return new Configuration((int)from.getValue(),(int)to.getValue(),(String)level.getSelectedItem(),selected,extra.getText());
        }
        void setInputsEnabled(boolean enabled) {enableTree(this,enabled);}
        private static void enableTree(Container parent,boolean enabled) {
            for(Component child:parent.getComponents()){child.setEnabled(enabled);if(child instanceof Container nested)enableTree(nested,enabled);}
        }
    }

    private static JPanel stack(){JPanel p=new JPanel();p.setOpaque(false);p.setLayout(new BoxLayout(p,BoxLayout.Y_AXIS));return p;}
    private static JPanel block(JComponent child) {
        JPanel wrapper=new JPanel(new BorderLayout()){
            @Override public Dimension getMaximumSize(){return new Dimension(Integer.MAX_VALUE,getPreferredSize().height);}
        };
        wrapper.setOpaque(false);wrapper.setAlignmentX(Component.LEFT_ALIGNMENT);wrapper.add(child);
        return wrapper;
    }
    private static JLabel label(String text,int size,Color color,int style) {
        JLabel label=MistWorkspaceTheme.label(text,size,color,style);label.putClientProperty("synesis.preserveFont",true);
        label.setAlignmentX(Component.LEFT_ALIGNMENT);return label;
    }
    private static JTextArea copy(String text,int size) {
        JTextArea area=new JTextArea(text){
            @Override public Dimension getMaximumSize(){return new Dimension(Integer.MAX_VALUE,getPreferredSize().height);}
        };
        area.setEditable(false);area.setFocusable(false);area.setOpaque(false);
        area.setLineWrap(true);area.setWrapStyleWord(true);area.setFont(StudyTheme.font(Font.PLAIN,size));area.setForeground(MistWorkspaceTheme.MUTED);
        area.setBorder(null);area.setAlignmentX(Component.LEFT_ALIGNMENT);area.putClientProperty("synesis.preserveFont",true);
        area.setMinimumSize(new Dimension(0,area.getFontMetrics(area.getFont()).getHeight()));
        return area;
    }
    private static void action(AbstractButton button) {
        MistWorkspaceTheme.button(button,true);button.setFont(StudyTheme.font(Font.PLAIN,12));
    }

    private static JComponent rule(Color color) {
        JPanel line=new JPanel();line.setBackground(color);line.setPreferredSize(new Dimension(1,1));
        return line;
    }

    private void styleSettingsToggle() {
        QuizSettingsStyle.button(settings,false);settings.setFont(StudyTheme.font(Font.BOLD,13));
        settings.setIcon(MistWorkspaceTheme.icon("gear",15));settings.setIconTextGap(10);
        settings.setBorder(new EmptyBorder(0,15,0,42));
        settings.setUI(new javax.swing.plaf.basic.BasicButtonUI(){
            @Override public void paint(Graphics graphics,JComponent component){
                Graphics2D g=(Graphics2D)graphics.create();
                try {
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    g.setColor(settings.getModel().isRollover()?QuizSettingsStyle.SOFT:Color.WHITE);
                    g.fillRoundRect(0,0,component.getWidth(),component.getHeight(),20,20);
                    g.setColor(settings.hasFocus()?QuizSettingsStyle.INK:QuizSettingsStyle.LINE);
                    g.drawRoundRect(0,0,component.getWidth()-1,component.getHeight()-1,20,20);
                    int x=component.getWidth()-24,y=component.getHeight()/2,sign=detailsHost.isExpanded()?-1:1;
                    g.setColor(QuizSettingsStyle.MUTED);g.setStroke(new BasicStroke(1.4f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                    g.drawLine(x-4,y-2*sign,x,y+2*sign);g.drawLine(x,y+2*sign,x+4,y-2*sign);
                }finally{g.dispose();}
                super.paint(graphics,component);
            }
        });
    }

    private void studioAction(AbstractButton button) {
        action(button);button.setForeground(STUDIO_INK);
        button.setBorder(new EmptyBorder(0,12,0,38));
        button.setPreferredSize(new Dimension(button.getFontMetrics(button.getFont()).stringWidth(button.getText())+50,34));
        button.setUI(new javax.swing.plaf.basic.BasicButtonUI(){
            @Override public void paint(Graphics graphics,JComponent component) {
                Graphics2D g=(Graphics2D)graphics.create();
                try {
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    g.setColor(button.getModel().isRollover()?MistWorkspaceTheme.SOFT:Color.WHITE);
                    g.fillRect(0,0,component.getWidth(),component.getHeight());
                    g.setColor(button.hasFocus()?STUDIO_INK:STUDIO_LINE);
                    g.drawRect(0,0,component.getWidth()-1,component.getHeight()-1);
                    if(button==settings) {
                        int x=component.getWidth()-25,y=component.getHeight()/2;
                        g.setColor(button.isEnabled()?STUDIO_INK:MistWorkspaceTheme.MUTED);g.drawOval(x-9,y-9,18,18);
                        g.drawLine(x-4,y,x+4,y);
                        if(!detailsHost.isExpanded())g.drawLine(x,y-4,x,y+4);
                    }
                } finally {g.dispose();}
                super.paint(graphics,component);
            }
        });
    }

    /** A quiet book spine in the local library; the selected preview remains the large cover. */
    private static final class WorkbookCoverIcon implements Icon {
        private final Theme theme;
        WorkbookCoverIcon(Theme theme){this.theme=theme;}
        public int getIconWidth(){return 54;}
        public int getIconHeight(){return 76;}
        public void paintIcon(Component component,Graphics graphics,int x,int y) {
            Graphics2D g=(Graphics2D)graphics.create();
            try {
                g.translate(x,y);g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                Color cover=switch(theme){case CONCEPT->new Color(0xc6a477);case UNDERSTANDING->new Color(0xd9e0f2);case PRACTICE->new Color(0x231511);case RECALL->new Color(0xf1dfb8);};
                g.setColor(new Color(0xd7d3c7));g.fillRect(4,3,49,72);
                g.setColor(cover);g.fillRect(0,0,49,71);g.setColor(new Color(0x34435a));g.fillRect(0,0,4,71);
                g.setColor(theme==Theme.PRACTICE?new Color(0x5b3227):new Color(0,0,0,18));
                for(int line=9;line<49;line+=8)g.drawLine(line,0,line,70);
                for(int line=6;line<71;line+=8)g.drawLine(4,line,48,line);
                g.setColor(theme==Theme.PRACTICE?new Color(0xff5835):STUDIO_INK);g.setFont(StudyTheme.font(Font.BOLD,9));
                String[] titleLines=theme.title.split(" ");
                for(int line=0;line<titleLines.length;line++)g.drawString(titleLines[line],9,22+line*12);
                g.setColor(theme==Theme.PRACTICE?new Color(0xf0442d):new Color(0xf05b42));g.fillRect(10,50,13,2);
                g.drawLine(10,61,42,61);
            } finally {g.dispose();}
        }
    }

    /** Native controls keep their input/accessibility behavior; only the surface moves. */
    private static final class CreateButton extends JButton {
        private static final float[] SHIMMER_STOPS={0,.5f,1};
        private static final Color[] SHIMMER_COLORS={new Color(0xffc1bd),Color.WHITE,new Color(0xffc1bd)};
        private boolean generating;
        private int progress;
        void setProgress(boolean active,int percent) {
            if(generating==active&&progress==percent)return;
            generating=active;progress=percent;updateMotion();repaint();
            getAccessibleContext().setAccessibleDescription(active?"문제집 생성 진행률 "+percent+"퍼센트":getText());
        }
        private final javax.swing.Timer motion=new javax.swing.Timer(16,event->advance());
        private final java.util.function.LongSupplier clock;
        private final java.util.function.BooleanSupplier windowActive;
        private Runnable stopObserving;
        private boolean animationDisposed,windowWasActive;
        private double hover,from,target;
        private long started;
        CreateButton() {
            this(System::nanoTime,null);
        }
        CreateButton(java.util.function.LongSupplier clock,java.util.function.BooleanSupplier windowActive) {
            super("문제 생성하기");
            this.clock=clock;
            this.windowActive=windowActive==null?()->dev.synesis.poc.ui.AnimationWindow.active(this):windowActive;
            putClientProperty("synesis.preserveButton",true);putClientProperty("synesis.preserveFont",true);
            setFont(StudyTheme.font(Font.BOLD,13));setBorder(new EmptyBorder(0,20,4,48));
            setPreferredSize(new Dimension(1,58));setOpaque(false);setContentAreaFilled(false);
            setBorderPainted(false);setFocusPainted(false);setRolloverEnabled(true);
            setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));motion.setCoalesce(true);
            getModel().addChangeListener(event->{
                double next=isEnabled()&&(getModel().isRollover()||getModel().isPressed())?1:0;
                if(next==target)return;
                if(isShowing()&&this.windowActive.getAsBoolean()&&!animationDisposed)advance();
                else if(isShowing()&&!Boolean.getBoolean("synesis.reduceMotion"))updateHover();
                from=hover;target=next;started=clock.getAsLong();
                if(isShowing()&&!Boolean.getBoolean("synesis.reduceMotion"))updateMotion();
                else {hover=from=target;motion.stop();repaint();}
            });
        }
        private void syncMotion() {
            if(!isShowing()){motion.stop();hover=from=target;windowWasActive=false;return;}
            if(animationDisposed||!windowActive.getAsBoolean()){motion.stop();windowWasActive=false;return;}
            if(!windowWasActive){
                if(!Boolean.getBoolean("synesis.reduceMotion"))updateHover();
                repaint();
            }
            windowWasActive=true;updateMotion();
        }
        private void updateMotion() {
            // Reuse the hover timer; steady generation only repaints the glyph area at ~30 Hz.
            boolean active=!animationDisposed&&isShowing()&&windowActive.getAsBoolean();
            if(!active)windowWasActive=false;
            if(active&&!Boolean.getBoolean("synesis.reduceMotion")&&(generating||hover!=target)){
                motion.setDelay(hover!=target?16:33);
                if(!motion.isRunning())motion.start();
            }else motion.stop();
        }
        private Rectangle textDamage() {
            FontMetrics fm=getFontMetrics(getFont());
            int height=getHeight()-5;
            return new Rectangle(18,(height-fm.getHeight())/2-2,fm.stringWidth(getText())+4,fm.getHeight()+4);
        }
        private void advance() {
            if(animationDisposed||!isShowing()||!windowActive.getAsBoolean()) {windowWasActive=false;motion.stop();return;}
            if(Boolean.getBoolean("synesis.reduceMotion")){motion.stop();return;}
            double previous=hover;
            updateHover();
            if(previous!=hover)repaint();
            else if(generating){
                Rectangle dirty=textDamage();
                if(getVisibleRect().intersects(dirty))repaint(dirty.x,dirty.y,dirty.width,dirty.height);
            }
            updateMotion();
        }
        private void updateHover() {
            double t=Math.min(1,Math.max(0,(clock.getAsLong()-started)/180_000_000d));
            hover=from+(target-from)*(1-Math.pow(1-t,3));
        }
        @Override protected void paintComponent(Graphics graphics) {
            Graphics2D g=(Graphics2D)graphics.create();
            try {
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                int width=getWidth()-5,height=getHeight()-5;
                boolean active=isEnabled()||generating;
                g.setColor(active?new Color(0x632320):new Color(0xbab7ae));g.fillRect(4,4,width,height);
                double offset=hover*2;g.translate(offset,offset);
                g.setColor(active?STUDIO_RED:new Color(0xead5d4));g.fillRect(0,0,width,height);
                if(generating) {
                    g.setColor(new Color(0xa62626));
                    g.fillRect(0,0,(int)Math.round(width*progress/100d),height);
                }
                g.setColor(active?new Color(0x892925):MistWorkspaceTheme.MUTED);g.drawRect(0,0,width-1,height-1);
                g.setColor(active?Color.WHITE:new Color(0x745956));
                g.setFont(getFont());FontMetrics fm=g.getFontMetrics();
                if(generating&&!Boolean.getBoolean("synesis.reduceMotion")){
                    float textWidth=Math.max(1,fm.stringWidth(getText()));
                    float phase=(clock.getAsLong()%2_400_000_000L)/2_400_000_000f;
                    float x=20+phase*textWidth*2-textWidth;
                    g.setPaint(new LinearGradientPaint(x,0,x+textWidth,0,SHIMMER_STOPS,
                        SHIMMER_COLORS,MultipleGradientPaint.CycleMethod.REPEAT));
                }
                g.drawString(getText(),20,(height-fm.getHeight())/2+fm.getAscent());
                g.setColor(active?Color.WHITE:new Color(0x745956));
                int x=width-20,y=height/2;g.drawLine(x-24,y,x,y);g.drawLine(x-6,y-5,x,y);g.drawLine(x-6,y+5,x,y);
                if(hasFocus()){g.setColor(Color.WHITE);g.drawRect(3,3,width-7,height-7);}
            } finally {g.dispose();}
        }
        private void disposeAnimation() {
            animationDisposed=true;windowWasActive=false;motion.stop();
            if(stopObserving!=null){stopObserving.run();stopObserving=null;}
        }
        @Override public void addNotify() {
            animationDisposed=false;super.addNotify();
            if(stopObserving==null)stopObserving=dev.synesis.poc.ui.AnimationWindow.watch(this,this::syncMotion);
            syncMotion();
        }
        @Override public void removeNotify(){disposeAnimation();hover=from=target;super.removeNotify();}
    }

    /** Keeps a book-and-controls spread when space allows and stacks it in the PDF split pane. */
    private static final class BuilderArea extends JPanel implements LayoutManager {
        private final JComponent cover,controls;
        BuilderArea(JComponent cover,JComponent controls) {
            this.cover=cover;this.controls=controls;setOpaque(false);setLayout(this);add(cover);add(controls);
        }
        private int availableWidth(){return getWidth()>0?getWidth():getParent()!=null&&getParent().getWidth()>0?getParent().getWidth():400;}
        private int height(JComponent child,int width) {
            if(child.getWidth()!=width){child.setSize(width,child.getHeight());child.invalidate();}
            return child.getPreferredSize().height;
        }
        @Override public Dimension preferredLayoutSize(Container parent) {
            int width=availableWidth();
            if(width>=600){int left=(int)((width-24)*.46);return new Dimension(width,Math.max(height(cover,left),height(controls,width-left-24)));}
            return new Dimension(width,height(cover,width)+18+height(controls,width));
        }
        @Override public Dimension minimumLayoutSize(Container parent){return new Dimension(0,preferredLayoutSize(parent).height);}
        @Override public void layoutContainer(Container parent) {
            int width=getWidth();
            if(width>=600) {
                int left=(int)((width-24)*.46);
                cover.setBounds(0,0,left,height(cover,left));
                controls.setBounds(left+24,0,width-left-24,height(controls,width-left-24));
            } else {
                int coverHeight=height(cover,width);cover.setBounds(0,0,width,coverHeight);
                controls.setBounds(0,coverHeight+18,width,height(controls,width));
            }
        }
        @Override public void addLayoutComponent(String name,Component component){}
        @Override public void removeLayoutComponent(Component component){}
    }
    /** FlowLayout wraps its children but does not normally include extra rows in its height. */
    static final class WrapRow extends JPanel {
        private final int horizontalGap,verticalGap;
        WrapRow(int horizontalGap,int verticalGap) {
            super(new FlowLayout(FlowLayout.LEFT,horizontalGap,verticalGap));
            this.horizontalGap=horizontalGap;this.verticalGap=verticalGap;setOpaque(false);
            addComponentListener(new java.awt.event.ComponentAdapter(){
                @Override public void componentResized(java.awt.event.ComponentEvent event){revalidate();}
            });
        }
        @Override public Dimension getPreferredSize() {
            Insets insets=getInsets();
            int width=getWidth()>0?getWidth():getParent()!=null&&getParent().getWidth()>0?getParent().getWidth():400;
            int available=Math.max(1,width-insets.left-insets.right-2*horizontalGap);
            int rowWidth=0,rowHeight=0,height=insets.top+insets.bottom+2*verticalGap,maxWidth=0;
            for(Component child:getComponents())if(child.isVisible()) {
                Dimension size=child.getPreferredSize();
                if(rowWidth>0&&rowWidth+horizontalGap+size.width>available) {
                    height+=rowHeight+verticalGap;maxWidth=Math.max(maxWidth,rowWidth);rowWidth=0;rowHeight=0;
                }
                rowWidth+=(rowWidth>0?horizontalGap:0)+size.width;rowHeight=Math.max(rowHeight,size.height);
            }
            height+=rowHeight;maxWidth=Math.max(maxWidth,rowWidth);
            return new Dimension(Math.min(width,maxWidth+insets.left+insets.right+2*horizontalGap),height);
        }
        @Override public Dimension getMinimumSize(){return new Dimension(0,getPreferredSize().height);}
    }
    private static final class Column extends JPanel implements Scrollable {
        Column(){setLayout(new BoxLayout(this,BoxLayout.Y_AXIS));setBackground(STUDIO_PAPER);}
        public Dimension getPreferredScrollableViewportSize(){return new Dimension(500,600);}
        public int getScrollableUnitIncrement(Rectangle r,int orientation,int direction){return 24;}
        public int getScrollableBlockIncrement(Rectangle r,int orientation,int direction){return Math.max(24,r.height-40);}
        public boolean getScrollableTracksViewportWidth(){return true;}
        public boolean getScrollableTracksViewportHeight(){return getParent()!=null&&getPreferredSize().height<getParent().getHeight();}
    }
}
