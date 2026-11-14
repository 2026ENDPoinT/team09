package dev.synesis.poc.pdf;
import dev.synesis.poc.UiFonts;
import dev.synesis.poc.StudyFontSettings;
import dev.synesis.poc.ui.StudyTheme;
import dev.synesis.poc.ui.LibraryDesign;
import dev.synesis.poc.ui.MistWorkspaceTheme;
import dev.synesis.poc.ui.PanelCloseButtons;
import dev.synesis.poc.ui.GrowingTutorInput;

import dev.synesis.poc.ui.SmoothScrollPane;
import dev.synesis.poc.ui.SplitDividerHitLayer;
import dev.synesis.poc.ui.LayoutMotionPanel;

import com.google.gson.*;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import javax.swing.filechooser.FileNameExtensionFilter;
import javax.swing.plaf.LayerUI;
import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.datatransfer.*;
import java.awt.dnd.*;
import java.awt.event.InputEvent;
import java.awt.event.HierarchyEvent;
import java.awt.event.KeyEvent;
import java.awt.event.MouseWheelEvent;
import java.awt.event.MouseEvent;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.List;
import java.util.*;
import java.util.prefs.Preferences;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;
import java.util.stream.Stream;

/** PDF viewing, local indexing and explicitly authorized grounded generation, isolated from audio. */
public final class PdfWorkspace extends JPanel implements AutoCloseable {
    public record DisplaySettings(String pdfQuality,int summaryFont,int conceptFont,int tutorFont,int quizFont) {
        public DisplaySettings(String pdfQuality,int summaryFont,int conceptFont,int tutorFont) {
            this(pdfQuality,summaryFont,conceptFont,tutorFont,summaryFont);
        }
    }
    private static final Preferences DISPLAY_PREFERENCES = dev.synesis.poc.UserPreferences.forPackage(PdfWorkspace.class);
    public static DisplaySettings displaySettings() {
        String quality=DISPLAY_PREFERENCES.get("pdfQuality","일반");
        if(!List.of("저화질","일반","고화질").contains(quality))quality="일반";
        StudyFontSettings fonts=legacyStudyFonts();
        try {
            fonts=StudyFontSettings.read(fonts);
        } catch (IOException unavailable) {
            // Keep the study window usable even if the settings file cannot be read.
        }
        return new DisplaySettings(quality, fonts.summaryFont(), fontPreference("conceptFont",16), fonts.tutorFont(),
            fontPreference("quizFont",fontPreference("summaryFont",16)));
    }
    public static StudyFontSettings legacyStudyFonts() {
        return new StudyFontSettings(fontPreference("summaryFont",StudyFontSettings.SUMMARY_DEFAULT),
            fontPreference("tutorFont",StudyFontSettings.TUTOR_DEFAULT));
    }
    private static int fontPreference(String key, int fallback) {
        return Math.max(StudyFontSettings.MIN,Math.min(StudyFontSettings.MAX,DISPLAY_PREFERENCES.getInt(key,fallback)));
    }
    public static void saveDisplaySettings(DisplaySettings settings) throws IOException {
        new StudyFontSettings(settings.summaryFont(),settings.tutorFont()).save();
        DISPLAY_PREFERENCES.put("pdfQuality",settings.pdfQuality());
        DISPLAY_PREFERENCES.putInt("conceptFont",settings.conceptFont());
        DISPLAY_PREFERENCES.putInt("quizFont",settings.quizFont());
    }
    /** Property-change events are emitted on Swing's event thread when the document or page changes. */
    public static final String PDF_LOCATION_PROPERTY = "pdfLocation";
    public static final String PDF_OPENED_PROPERTY = "pdfOpened";
    public static final String PDF_OPEN_FAILED_PROPERTY = "pdfOpenFailed";
    public static final String PDF_PREPARED_PROPERTY = "pdfPrepared";
    public static final String PDF_PREPARE_FAILED_PROPERTY = "pdfPrepareFailed";
    public static final String GENERATION_PROGRESS_PROPERTY = "generationProgress";
    public record PdfLocation(String documentId, int page, int pageCount) {}
    public record GenerationProgress(String documentId, String documentName, int percent,
                                     String stage, boolean finished, boolean failed, boolean needsReview) {
        public GenerationProgress(String documentId,String documentName,int percent,String stage,
                                  boolean finished,boolean failed) {
            this(documentId,documentName,percent,stage,finished,failed,false);
        }
    }
    private static final Color INK = StudyTheme.INK, MUTED = StudyTheme.MUTED, BLUE = StudyTheme.ACCENT;
    private static final Color TUTOR_USER_FILL = MistWorkspaceTheme.SOFT, TUTOR_ASSISTANT_FILL = Color.WHITE;
    private static final Gson JSON = new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create();
    private static final String GENERATION_PROMPT_VERSION = "pdf-grounded-ko-v56-learner";
    private static final String SEMANTIC_VERSION = "semantic-v1";
    static final String LOCAL_HIERARCHY_VERSION="study-hierarchy-7";
    static final String LOCAL_HIERARCHY_DISPLAY_REVISION="source-unit-continuity-3";
    private static final String[] STRATEGY_IDS = Stream.concat(
        Stream.of(SEMANTIC_VERSION,"page-v1","region-v1","region-local-v1","slide-v1","new-concept-v1","new-concept-v02"),
        Arrays.stream(PdfStudyStrategy.ENGINE_IDS)).toArray(String[]::new);
    private static final String[] STRATEGY_LABELS = Stream.concat(
        Stream.of("의미 단위_기존 방식","페이지 단위_기존 방식","개념 영역_실험","로컬 영역_실험",
            "페이지 직접 생성_실험","New개념Ver_초기 개념 해설","ver.0.2_원문 기반 개념"),
        Arrays.stream(PdfStudyStrategy.ENGINE_LABELS)).toArray(String[]::new);
    private static final Set<String> STREAMING_OVERVIEW_STRATEGIES = Set.of("newest-k1-2-3","newest-k1-2-4","newest-k1-2-5");
    private final JComboBox<String> summaryStrategy = new JComboBox<>(STRATEGY_LABELS);
    private final JButton strategyComparison = new JButton("방식별 결과 비교");
    private final JButton semanticCoverage = new JButton("처리 내역");
    private final ExecutorService files = executor("pdf-files"), jobs = executor("pdf-analysis"),
        tutorJobs = executor("pdf-tutor"), renders = executor("pdf-render");
    private final PdfProcess processes = new PdfProcess(), tutorProcesses = new PdfProcess();
    PdfStudyQueue studyQueue=PdfStudyQueue.global();
    private StudyAdmission studyAdmission;
    private final class StudyAdmission {
        volatile boolean cancelled,waiting=true;
        volatile Future<?> future;
        volatile PdfStudyQueue.Permit permit;
        void release() {
            cancelled=true;
            Future<?> pending=future;if(pending!=null)pending.cancel(true);
            PdfStudyQueue.Permit owned=permit;if(owned!=null)processes.afterIdle(owned::close);
        }
    }
    @FunctionalInterface interface SavedHierarchyRecovery {
        JsonObject recover(PdfSource source,int ticket,String strategy,String scope,int page,String fingerprint);
    }
    SavedHierarchyRecovery savedHierarchyRecovery=this::recoverSavedHierarchy;
    private record HierarchyProjectionAttempt(PdfSource source,JsonObject document,int epoch,int ticket,JsonObject product) {}
    private final Map<String,HierarchyProjectionAttempt> hierarchyProjectionAttempts=new ConcurrentHashMap<>();
    private final AtomicInteger generation = new AtomicInteger(), renderGeneration = new AtomicInteger(),
        tutorGeneration = new AtomicInteger();
    private boolean initialPdfEntrance;
    private final JLabel filename = new JLabel("강의자료"), status = new JLabel("PDF를 끌어오거나 불러오기를 눌러 주세요.");
    private final JLabel pageLabel = MistWorkspaceTheme.label("/ 0",12,MistWorkspaceTheme.MUTED,Font.PLAIN);
    private final JLabel tutorConnection = MistWorkspaceTheme.badge("PDF 연결 대기");
    private final JLabel tutorDocumentConnection = MistWorkspaceTheme.label("PDF · 약한 연결",10,MistWorkspaceTheme.MUTED,Font.PLAIN);
    private GrowingTutorInput tutorInputCard;
    private final JButton expandPdf = MistWorkspaceTheme.iconButton("expand","PDF 전체보기",16);
    private JPanel pdfReadingArea;
    private JPanel pdfOnlyScreen;
    private Consumer<JComponent> pdfOnlyOpener;
    private boolean quizExpansionCycle;
    private Runnable pdfOnlyReturn;
    private final Map<String,JLabel> tutorTimeLabels = new HashMap<>();
    private final Set<String> likedTutorAnswers = new HashSet<>();
    private final List<JButton> tutorFollowUps = new ArrayList<>();
    private final javax.swing.Timer tutorTimeTimer = new javax.swing.Timer(15_000,e->refreshTutorTimes());
    private final JSpinner pageNumber = new JSpinner(new SpinnerNumberModel(1, 1, 1, 1));
    private final JPanel pdfPageNavigation = new JPanel(new FlowLayout(FlowLayout.LEFT,4,0));
    private JPanel pdfNavigation;
    private static final int[] PDF_ZOOM_STEPS = {25, 33, 50, 75, 90, 100, 125, 150, 175, 200, 250, 300, 400, 500};
    private final JComboBox<String> zoom = pdfZoomSelector("너비 맞춤");
    private final JComboBox<String> fullZoom = pdfZoomSelector("100%");
    private boolean updatingPdfZoom;
    private final JButton zoomOut = new JButton("−"), zoomIn = new JButton("+");
    private final JButton thumbnailToggle = MistWorkspaceTheme.iconButton("page-index","페이지 목록 열기",16);
    private final JComboBox<String> scope = new JComboBox<>(new String[]{"전체 자료", "현재 페이지", "현재 5쪽 범위"});
    private final JComboBox<String> studyScope = new JComboBox<>(scope.getModel());
    private final boolean autoGenerateOnImport;
    private final boolean automaticStudy;
    private final Path pdfStorageRoot;
    private final JButton cancel = new JButton("취소"), retry = new JButton("추출 재시도"), generate = new JButton("PDF 강의 해설·개념 정리 생성"), regenerate = new JButton("최신 규칙으로 생성");
    private final JButton comparisonResults = new JButton("이전 비교 결과 보기");
    private final JButton visual = new JButton("이 페이지 전체 분석");
    private final JButton analyzeImages = new JButton("자료 페이지 분석");
    private final JButton imageReport = new JButton("페이지 분석 결과");
    private final JButton ask = new JButton("보내기"), newChat = new JButton("새 채팅");
    private final JButton tutorAttach = new JButton("+"), tutorClearAttachment = new JButton("×");
    private final JLabel tutorAttachmentLabel = new JLabel();
    private final JPanel tutorAttachmentPreviews = new JPanel(new FlowLayout(FlowLayout.LEFT,6,4));
    private final List<Path> tutorAttachments = new ArrayList<>();
    private final Set<Path> tutorPastedAttachments = new HashSet<>();
    private final Map<Path,TutorPreview> tutorAttachmentThumbnails = new HashMap<>();
    private final JComboBox<String> tutorMode = new JComboBox<>(new String[]{"간단한 설명", "상세한 설명"});
    private final JComboBox<String> tutorReasoning = new JComboBox<>(new String[]{"높은 추론", "중간 추론"});
    private final JLabel tutorSearchHint = new JLabel("필요할 때 외부 검색 · 끄려면 ‘검색하지 마’라고 입력");
    private final SummaryActivityBar summaryActivity=new SummaryActivityBar();
    private final SummaryOverviewLoading summaryOverviewLoading=new SummaryOverviewLoading(summaryActivity);
    private long summaryScrollInteraction,summaryScrollRequest;
    private boolean restoringSummaryScroll;
    private final JButton summaryOutlineButton=new JButton("목차");
    private final SummaryOutlinePopup summaryOutlinePopup=new SummaryOutlinePopup();
    private final SummaryOutlineTree summaryOutlineTree=new SummaryOutlineTree();
    private List<SummaryOutline.Entry> summaryOutlineEntries=List.of();
    private final Map<String,javax.swing.tree.TreePath> summaryOutlinePaths=new HashMap<>();
    private Map<String,SummaryOutline.Target> summaryOutlineTargets=Map.of();
    private final NavigableMap<Integer,String> summaryOutlineOffsets=new TreeMap<>();
    private record OutlineAnchor(String id,int offset) {}
    private final JTextField search = new dev.synesis.poc.ui.AccessibleInputs.TextField();
    private final JTextArea question = new dev.synesis.poc.ui.AccessibleInputs.TextArea() {
        @Override protected void paintComponent(Graphics graphics) {
            super.paintComponent(graphics);
            if(!getText().isEmpty())return;
            Graphics2D copy=(Graphics2D)graphics.create();
            try {
                copy.setColor(MistWorkspaceTheme.MUTED);
                copy.setFont(getFont());
                copy.drawString("궁금한 내용을 물어보세요",getInsets().left,
                    getInsets().top+copy.getFontMetrics().getAscent());
            } finally {copy.dispose();}
        }
    };
    private boolean summaryReadingSkin=!Boolean.getBoolean("synesis.legacySummarySkin")
        && DISPLAY_PREFERENCES.getBoolean("summaryReadingSkin",true);
    private final Map<Integer,JEditorPane> summaryProsePanes=new HashMap<>();
    private final Map<String,MathScrollPane> summaryMathPanes=new HashMap<>();
    private final Map<String,SummaryFormulaGroup> summaryFormulaGroups=new HashMap<>();
    private final JEditorPane summary = html(true), original = html(), visualDetail = html();
    private final JScrollPane originalScroll = new SmoothScrollPane(null);
    private boolean originalDirty = true;
    private Point originalScrollPosition = new Point();
    private final JScrollPane summaryScroll = new SmoothScrollPane(summary) {
        @Override protected void processMouseWheelEvent(MouseWheelEvent event) {
            summaryScrollInteraction++;super.processMouseWheelEvent(event);
        }
    };
    private final StudyScrollActivity summaryScrollActivity=new StudyScrollActivity(summaryScroll,this::summaryScrollActivityChanged);
    private BufferedImage summaryFadeSnapshot;
    private double summaryFadeScaleX,summaryFadeScaleY;
    private final JLayer<JScrollPane> summaryFadeLayer = new JLayer<>(summaryScroll,new LayerUI<>() {
        @Override public void uninstallUI(JComponent component) {
            ((JLayer<?>)component).setLayerEventMask(0);super.uninstallUI(component);
        }
        @Override protected void processMouseEvent(MouseEvent event,JLayer<? extends JScrollPane> layer) {
            if(event.getID()==MouseEvent.MOUSE_PRESSED)interruptSummaryFade();
        }
        @Override protected void processMouseMotionEvent(MouseEvent event,JLayer<? extends JScrollPane> layer) {
            if(event.getID()==MouseEvent.MOUSE_DRAGGED)interruptSummaryFade();
        }
        @Override protected void processMouseWheelEvent(MouseWheelEvent event,JLayer<? extends JScrollPane> layer){interruptSummaryFade();}
        @Override protected void processKeyEvent(KeyEvent event,JLayer<? extends JScrollPane> layer){if(event.getID()==KeyEvent.KEY_PRESSED)interruptSummaryFade();}
        @Override public void paint(Graphics graphics,JComponent component) {
            if(summaryFadeAlpha<=0) {summaryFadeSnapshot=null;super.paint(graphics,component);return;}
            Graphics2D overlay=(Graphics2D)graphics.create();
            try {
                double sx=Math.abs(overlay.getTransform().getScaleX()),sy=Math.abs(overlay.getTransform().getScaleY());
                double cap=Math.min(1,Math.sqrt(8_388_608d/Math.max(1,component.getWidth()*(double)component.getHeight()*sx*sy)));
                sx*=cap;sy*=cap;
                int width=Math.max(1,(int)Math.ceil(component.getWidth()*sx)),height=Math.max(1,(int)Math.ceil(component.getHeight()*sy));
                if(summaryFadeSnapshot==null || summaryFadeSnapshot.getWidth()!=width || summaryFadeSnapshot.getHeight()!=height
                        || summaryFadeScaleX!=sx || summaryFadeScaleY!=sy) {
                    summaryFadeSnapshot=new BufferedImage(width,height,BufferedImage.TYPE_INT_RGB);
                    Graphics2D frame=summaryFadeSnapshot.createGraphics();
                    try {frame.scale(sx,sy);summaryScroll.printAll(frame);}
                    finally {frame.dispose();}
                    summaryFadeScaleX=sx;summaryFadeScaleY=sy;
                }
                Graphics2D pixels=(Graphics2D)overlay.create();
                try {pixels.scale(1/sx,1/sy);pixels.drawImage(summaryFadeSnapshot,0,0,null);}
                finally {pixels.dispose();}
                overlay.setComposite(AlphaComposite.SrcOver.derive(summaryFadeAlpha));
                overlay.setColor(StudyTheme.PAPER);
                overlay.fillRect(0,0,component.getWidth(),component.getHeight());
            } finally {overlay.dispose();}
        }
    });
    private final SummaryOutlineHover summaryOutlineHover=new SummaryOutlineHover(summaryScroll,summaryOutlineButton,summaryOutlinePopup,
        ()->!summaryOutlineEntries.isEmpty(),this::refreshSummaryOutlineTree,this::updateSummaryOutlineSelection);
    private javax.swing.Timer summaryFadeTimer;
    private float summaryFadeAlpha;
    private boolean pendingSavedSummaryFade;
    private final SummaryFlow summaryFlow = new SummaryFlow(80);
    private final SummaryFlow summaryOverviewContent = new SummaryFlow();
    private static final Pattern SLIDE_LENS_MARKER = Pattern.compile(
        "<!--(?:SLIDELENS:([A-Za-z0-9:/._-]+)|MATHSCROLL:([A-Za-z0-9]+)|(READINGBREAK)|FORMULAGROUP:([0-9]+)|(SUMMARYACTIVITY))-->");
    private static final Pattern SUMMARY_CONTENT_MARKER = Pattern.compile(
        SLIDE_LENS_MARKER.pattern()+"|<!--(OVERVIEWSTART|LIVEOVERVIEWSTART)-->|<!--(OVERVIEWEND)-->|<!--SUMMARYSTREAM:([0-9]+)-->|<!--SUMMARYSPACE:([0-9]+)-->");
    private static final Pattern SLIDE_LENS_INLINE = Pattern.compile("(?m)^[ \\t]*\\[\\[SLIDE_LENS\\]\\][ \\t]*(?:\\r?\\n|$)");
    private final JButton applyVisual = new JButton("이거 반영해서 강의 해설/개념 설명 고치기");
    private final DisplaySettings initialDisplaySettings = displaySettings();
    private String pdfQuality = initialDisplaySettings.pdfQuality();
    private final JSlider summaryFontSize = new JSlider(6, 64, initialDisplaySettings.summaryFont());
    private final JLabel summaryFontValue = new JLabel(initialDisplaySettings.summaryFont() + "px");
    private final JSlider conceptFontSize = new JSlider(6, 64, initialDisplaySettings.conceptFont());
    private final JLabel conceptFontValue = new JLabel(initialDisplaySettings.conceptFont() + "pt");
    private final JSlider tutorFontSize = new JSlider(6, 64, initialDisplaySettings.tutorFont());
    private final JLabel tutorFontValue = new JLabel(initialDisplaySettings.tutorFont() + "px");
    private final JPanel recoveryRow = row();
    private final JPanel conceptList = new VerticalList(), imageCanvas = new JPanel(new GridBagLayout()) {
        @Override protected void paintComponent(Graphics graphics) {super.paintComponent(graphics);paintPdfPages(graphics);}
    }, thumbnailCanvas = new JPanel() {
        @Override protected void paintComponent(Graphics graphics) {super.paintComponent(graphics);paintThumbnails(graphics);}
    };
    private final JScrollPane conceptScroll = new SmoothScrollPane(conceptList);
    private ConceptOverview conceptOverview;
    private final Map<String,ConceptOverview.Card> conceptCards=new LinkedHashMap<>();
    private String conceptProduct="";
    private final JLabel pageImage = new JLabel("PDF를 여기에 끌어다 놓으세요", SwingConstants.CENTER);
    private final JScrollPane imageScroll = new SmoothScrollPane(imageCanvas) {
        @Override protected void processMouseWheelEvent(java.awt.event.MouseWheelEvent event) {
            if(event.isControlDown() && source!=null && sourceTabs.getSelectedIndex()==0) {
                zoomPdfWithWheel(event);
                event.consume();
            } else super.processMouseWheelEvent(event);
        }
    };
    private final JScrollPane thumbnailScroll = new SmoothScrollPane(thumbnailCanvas);
    private final DefaultListModel<JsonObject> searchItems = new DefaultListModel<>();
    private final JList<JsonObject> searchResults = new JList<>(searchItems);
    private final JPanel searchPanel = new JPanel(new BorderLayout());
    private final LayoutMotionPanel viewer = new LayoutMotionPanel(new BorderLayout(),12,Color.WHITE,MistWorkspaceTheme.LINE);
    private JSplitPane studySplit;
    private boolean resizingPdf;
    private javax.swing.Timer studyTransition;
    private javax.swing.Timer sideStudyTransition;
    private JToggleButton pdfToggle;
    private boolean pdfVisible = true;
    private boolean learningVisible = true;
    private JPanel learningPanel;
    private final dev.synesis.poc.ui.StudyColumns studyColumns=new dev.synesis.poc.ui.StudyColumns();
    private final JPanel emptyStudy = new JPanel(new GridBagLayout());
    private final JLabel emptyStudyMessage = new JLabel("열린 창이 아무것도 없어요. 고요하네요.");
    private static final double INITIAL_PDF_RATIO = 0.465;
    private int dividerBeforePdfHide = -1;
    private ZoomAnchor hiddenPdfAnchor;
    private boolean sidePanelVisible;
    private int dividerBeforeSidePanel = 600;
    private final JTabbedPane sourceTabs = new JTabbedPane();
    private final DropOverlay overlay = new DropOverlay();
    private final JPanel dropContent = new JPanel(new BorderLayout());
    private final JLayer<JComponent> dropLayer = new JLayer<>(dropContent, overlay);
    private final JPanel studyActions = new JPanel(new BorderLayout(8, 0));
    private final JLabel automaticStudyStatus = new JLabel();
    private final JButton automaticStudyAction = new JButton();
    private String automaticStudyError;
    private final QuizPanel quiz = new QuizPanel();
    private final QuizBackgroundJobs backgroundQuizzes=new QuizBackgroundJobs();
    private final CardLayout rightCards = new CardLayout();
    private final JPanel rightContent = new JPanel(rightCards);
    private JPanel tutorPanel;
    private Runnable tutorSideOpener;
    private Runnable tutorSideCloser;
    private java.util.function.Consumer<List<Path>> pdfImportHandler;
    private final JPanel learningNavigation = new JPanel(new BorderLayout());
    private final JPanel learningNavigationTabs=new dev.synesis.poc.ui.StudyTabStrip();

    public void monitorStudyRatio(boolean outerTransitioning) {
        if(studySplit instanceof dev.synesis.poc.ui.ProportionalSplitPane split)
            split.monitorRatio(pdfVisible+":"+learningVisible+":"+sidePanelVisible,
                outerTransitioning || studyTransition!=null || sideStudyTransition!=null);
    }

    private final ButtonGroup learningTabs = new ButtonGroup();
    private final Map<String,JToggleButton> tabButtons = new HashMap<>();
    private String selectedLearningTab = "요약";
    private final Map<String,JsonObject> visualNotices = new HashMap<>();
    private final Set<String> expandedEasySummaries = new HashSet<>();
    private final Set<String> expandedSlideLens = new HashSet<>(), pendingSlideLens = new HashSet<>();
    private final Map<String,Integer> loadingSummaryLensAnchors = new HashMap<>();
    private final Map<String,Integer> slideLensWidths = new HashMap<>();
    private final Map<String,StepFlow.Model> summaryStepFlows = new LinkedHashMap<>();
    private final Map<String,Integer> selectedSteps = new HashMap<>();
    private final Map<String,BufferedImage> slideLensImages = new LinkedHashMap<>(32,.75f,true) {
        @Override protected boolean removeEldestEntry(Map.Entry<String,BufferedImage> eldest) { return size()>32; }
    };
    private final Map<String,String> slideLensErrors = new HashMap<>();
    private final Set<String> expandedConcepts = new HashSet<>(), expandedEasyConcepts = new HashSet<>();
    private volatile PdfSource source;
    private volatile JsonObject index;
    private JsonObject generated;
    private JsonObject comparisonReport;
    private final Map<String,JsonObject> products = new HashMap<>();
    private final Map<Integer,JsonObject> liveSummarySections = new TreeMap<>();
    // Unverified arriving text is display-only. It never becomes a saved
    // product, a completed unit, evidence, or a concept card.
    private final Map<Integer,JsonObject> liveSummaryDrafts = new TreeMap<>();
    private final Map<Integer,Long> liveSummaryDraftSequences = new HashMap<>();
    private final Map<Integer,JEditorPane> liveSummaryDraftPanes = new HashMap<>();
    private final Map<Integer,SummaryStreamSpace> liveSummarySpaces = new TreeMap<>();
    private javax.swing.Timer liveSummaryMotionTimer;
    private final Set<Integer> liveSummaryDiscarded = new HashSet<>();
    private javax.swing.Timer liveSummaryDraftTimer;
    private boolean liveSummaryDraftStructureDirty;
    private final Map<Integer,JsonArray> liveConceptUnits = new TreeMap<>();
    private final Map<Integer,Integer> liveSummaryVisible = new HashMap<>();
    private final Map<Integer,TutorStreamFade> liveSummaryFades = new HashMap<>();
    private String liveGenerationKey;
    private JsonObject liveOverview;
    private JEditorPane liveOverviewStreamPane,liveOverviewEvidencePane;
    private boolean liveOverviewStreaming,liveOverviewComplete;
    private long liveOverviewSequence;
    private boolean generationEngineSelected;
    private volatile boolean externalBatchActive;
    private volatile long observedBatchOrder=-1,liveBatchOrder=-1;
    private int liveSummaryTotal;
    private javax.swing.Timer liveSummaryTimer;
    private javax.swing.Timer liveSummaryRefreshTimer;
    private Runnable liveSummaryCompletion;
    private volatile int page = 1;
    private record PageLayout(int number, Rectangle bounds, float renderScale) {}
    private record ZoomAnchor(int page, double xFraction, double yFraction, int viewportX, int viewportY) {}
    private ZoomAnchor pendingLayoutAnchor;
    private ZoomAnchor panelLayoutAnchor;
    private boolean outerPanelLayoutChanging;
    private final javax.swing.Timer panelAnchorTimer=new javax.swing.Timer(140,e->finishPanelPageLayout());
    private double zoomWheelAccumulation;
    private long lastZoomWheelNanos;
    private final PdfZoomMotion pdfZoomMotion=new PdfZoomMotion(()->imageCanvas.repaint());
    private double zoomMotionBasePercent;
    private ZoomAnchor zoomMotionAnchor;
    private final Map<Integer,Float> pageBitmapScales=new HashMap<>();
    private final List<PageLayout> pageLayouts = new ArrayList<>();
    private final List<Rectangle> thumbnailLayouts = new ArrayList<>();
    private final PdfTextSelection textSelection = new PdfTextSelection();
    private final Map<Integer,BufferedImage> pageBitmaps = new HashMap<>(), thumbnailBitmaps = new HashMap<>();
    private final Set<Integer> pendingPages = new HashSet<>(), pendingThumbnails = new HashSet<>();
    private volatile Set<Integer> wantedPages = Set.of(), wantedThumbnails = Set.of();
    private final javax.swing.Timer scrollPageTimer = new javax.swing.Timer(100,e->updatePageFromScroll());
    private int lastScrollY;
    private int lastViewportWidth;
    private int lastViewportHeight;
    private boolean programmaticScroll, rebuildingViewer;
    private boolean selectingImage;
    private int selectionPage;
    private static final int THUMB_WIDTH = 118;
    private boolean closed, busy, tutorBusy, quizGenerating;
    private CompletableFuture<Void> closeCompletion;
    private boolean studyViewsWereVisible,summaryRenderPending,conceptRenderPending;
    private long quizWorkbookOpenRevision;
    private GenerationProgress generationProgress;
    private boolean firstSummaryShown;
    private Runnable pendingGenerationReport;
    private JsonObject tutorMemory = new JsonObject();
    private final List<TutorTurn> conversation = new ArrayList<>();
    private final Map<String,JsonObject> tutorAnswers = new HashMap<>();
    private final Set<String> expandedTutorEvidence = new HashSet<>();
    private final CardLayout tutorCards = new CardLayout();
    private final JPanel tutorBody = new JPanel(tutorCards);
    private final TutorMessageColumn tutorMessages = new TutorMessageColumn();
    private final JScrollPane tutorScroll = new SmoothScrollPane(tutorMessages) {
        @Override protected void processMouseWheelEvent(java.awt.event.MouseWheelEvent event) {
            TutorScrollKeeper keeper=TutorScrollKeeper.owner(this);
            if(keeper!=null && !event.isConsumed() && !event.isShiftDown() && !event.isControlDown()
                    && isWheelScrollingEnabled())keeper.wheelInput(event.getPreciseWheelRotation());
            super.processMouseWheelEvent(event);
        }
    };
    private final TutorScrollKeeper tutorScrollKeeper=new TutorScrollKeeper(tutorScroll,tutorMessages);
    private final Map<String,StudySelectionContext.Source> summarySelectionSources=new HashMap<>(),conceptSelectionSources=new HashMap<>();
    private final StudySelectionActions summarySelection=new StudySelectionActions(summaryFlow,
        this::askSelectedStudy,()->index!=null&&!tutorBusy,message->status.setText(message));
    private final StudySelectionActions conceptSelection=new StudySelectionActions(conceptList,
        this::askSelectedStudy,()->index!=null&&!tutorBusy,message->status.setText(message));
    private String activeTutorMarker, streamingTutorText = "";
    private final TutorTextReveal tutorTextReveal=new TutorTextReveal();
    private Runnable tutorStreamCompletion;
    private final TutorActivity tutorActivity=new TutorActivity(this::refreshTutorActivity);
    private long lastTutorStreamPaint;
    private final TutorStreamFade tutorStreamFade = new TutorStreamFade(0xffffff,0x45474c);
    private final javax.swing.Timer tutorFadeTimer = new javax.swing.Timer(40,event->refreshTutorFade());
    // Smooth decorative motion is independent of the more expensive text/layout cadence.
    private final javax.swing.Timer tutorThinkingTimer = new javax.swing.Timer(16,event->{
        if(this.streamingTutorBubble!=null&&dev.synesis.poc.ui.AnimationWindow.active(tutorPanel))
            this.streamingTutorBubble.thinkingLabel.repaint();
        else ((javax.swing.Timer)event.getSource()).stop();
    });
    private Runnable unwatchTutor=()->{};
    private RoundedTutorBubble streamingTutorBubble;
    private final Map<String,RoundedTutorBubble> tutorBubbles = new HashMap<>();
    private final javax.swing.Timer tutorResizeTimer = new javax.swing.Timer(16,event->animateTutorBubbles());
    private final Deque<RoundedTutorBubble> tutorReflowQueue = new ArrayDeque<>();
    private final javax.swing.Timer tutorViewportResizeTimer = new javax.swing.Timer(16,event->reflowNextTutorBubble());
    private int tutorViewportWidth = -1;
    private String streamingTutorHtml = "";
    private int streamingTutorFontSize;
    private int streamingTutorMathWidth;
    private static final class TutorTurn {
        final String question, marker;
        final List<TutorPreview> previews;
        final boolean studySelection;
        String failure;
        long answeredAt;
        TutorTurn(String question,String marker,List<TutorPreview> previews){
            this(question,marker,previews,false);
        }
        TutorTurn(String question,String marker,List<TutorPreview> previews,boolean studySelection){
            this.question=question;this.marker=marker;this.previews=previews;this.studySelection=studySelection;
        }
    }
    private record TutorPreview(String name,ImageIcon icon) {}

    public PdfWorkspace() {
        this(true,PdfLibraryStore.defaultRoot());
    }
    public PdfWorkspace(boolean autoGenerateOnImport) {
        this(autoGenerateOnImport,PdfLibraryStore.defaultRoot());
    }
    public static PdfWorkspace automaticStudy() {
        return new PdfWorkspace(false,PdfLibraryStore.defaultRoot(),true);
    }
    PdfWorkspace(boolean autoGenerateOnImport,Path pdfStorageRoot) {
        this(autoGenerateOnImport,pdfStorageRoot,false);
    }
    private PdfWorkspace(boolean autoGenerateOnImport,Path pdfStorageRoot,boolean automaticStudy) {
        super(new BorderLayout());
        this.autoGenerateOnImport=autoGenerateOnImport;
        this.automaticStudy=automaticStudy;
        this.pdfStorageRoot=pdfStorageRoot;
        for(JScrollPane scroll:List.of(summaryScroll,conceptScroll,tutorScroll))
            ((SmoothScrollPane)scroll).setVerticalScrollReuseEnabled(true);
        summarySelection.setContext("강의 해설",summarySelectionSources,this::askSelectedStudy);
        conceptSelection.setContext("개념",conceptSelectionSources,this::askSelectedStudy);
        setFont(new Font(UiFonts.FAMILY, Font.PLAIN, 13));
        setBackground(StudyTheme.CANVAS);
        buildViewer();
        getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW).put(KeyStroke.getKeyStroke("ESCAPE"), "cancelImageSelection");
        getActionMap().put("cancelImageSelection", new AbstractAction() {
            @Override public void actionPerformed(java.awt.event.ActionEvent event) {
                if (selectingImage) {
                    exitImageSelection();
                    status.setText("이미지 선택을 취소했습니다.");
                }
            }
        });
        JPanel right = buildLearning();
        styleControls(right); // Includes study panels not mounted in either slot yet.
        buildStudyActions();
        quiz.setTutorRequestHandler(this::askQuizTutor);
        quiz.setCloseHandler(()->closeLearningTab("퀴즈로 학습하기"));
        quiz.setMaximizeHandler(this::toggleQuizMaximize);
        quiz.setConceptNavigation(question->QuizConceptLinks.resolve(question,conceptResultForDisplay()),this::openQuizConcept);
        quiz.setGenerationRequestHandler(this::startQuizGeneration);
        quiz.setWorkbookOpenHandler(this::openQuizWorkbook);
        quiz.setWorkbookProgressHandler(this::saveQuizWorkbookAnswers);
        quiz.setWorkbookManagementHandlers(this::renameQuizWorkbook,this::deleteQuizWorkbook);
        learningPanel=studyColumns;
        right=studyColumns;
        studyColumns.configure(count->{setLearningVisible(count>0);updateNavigationAddMarkers();},name->{
            selectedLearningTab=name;
            JToggleButton navigation=tabButtons.get(name);if(navigation!=null)navigation.setSelected(true);
            updateNavigationAddMarkers();
            setControls();
        },this::preservePdfPageForPanelLayout);
        emptyStudy.setBackground(StudyTheme.CANVAS);
        emptyStudyMessage.setFont(StudyTheme.font(Font.PLAIN,18));
        emptyStudyMessage.setForeground(MUTED);
        emptyStudy.add(emptyStudyMessage);
        StudyTheme.comboBox(zoom);
        StudyTheme.comboBox(scope);
        for(JComboBox<String> option:List.of(tutorMode,tutorReasoning)){
            StudyTheme.comboBox(option);option.setSelectedIndex(0);
            option.setFont(MistWorkspaceTheme.font(Font.PLAIN,12));option.setForeground(MistWorkspaceTheme.TEXT);option.setBackground(MistWorkspaceTheme.SOFT);
            option.putClientProperty("synesis.preserveFont",true);
        }
        tutorReasoning.setSelectedIndex(1);
        JSplitPane split = new dev.synesis.poc.ui.ProportionalSplitPane(
            JSplitPane.HORIZONTAL_SPLIT, viewer, right, INITIAL_PDF_RATIO);
        studySplit=split;
        split.setBorder(null); split.setDividerSize(4); split.setResizeWeight(0);
        if(split.getUI() instanceof javax.swing.plaf.basic.BasicSplitPaneUI ui){ui.getDivider().setBorder(null);ui.getDivider().setBackground(StudyTheme.CANVAS);}
        split.setContinuousLayout(true);
        split.setBackground(StudyTheme.CANVAS);
        viewer.setMinimumSize(new Dimension(300, 100)); right.setMinimumSize(new Dimension(340, 100));
        JPanel contentFrame=new JPanel(new BorderLayout());contentFrame.setBackground(StudyTheme.CANVAS);
        contentFrame.setBorder(BorderFactory.createEmptyBorder());
        contentFrame.add(new JLayer<>(split,new SplitDividerHitLayer()),BorderLayout.CENTER);
        dropContent.setBackground(StudyTheme.CANVAS);
        dropContent.add(learningNavigation,BorderLayout.NORTH);
        if(!automaticStudy)dropContent.add(studyActions,BorderLayout.SOUTH);
        dropContent.add(contentFrame, BorderLayout.CENTER);
        add(dropLayer, BorderLayout.CENTER);
        summary.setText(documentHtml("강의 해설", automaticStudy?"PDF를 열면 강의 해설을 자동으로 준비해요."
            :"PDF를 불러오면 페이지별 원문을 준비합니다.<br>강의 해설은 별도 실행으로 생성할 수 있습니다.",summaryFontSize.getValue()));
        renderTutor(false);
        conceptList.setLayout(new BoxLayout(conceptList, BoxLayout.Y_AXIS));
        conceptList.setBackground(Color.WHITE);
        conceptList.add(new JLabel("PDF 분석 후 개념을 생성해 주세요."));
        styleControls(this);
        MistWorkspaceTheme.comboBox(zoom,true);MistWorkspaceTheme.comboBox(tutorMode,false);MistWorkspaceTheme.comboBox(scope,true);
        MistWorkspaceTheme.comboBox(tutorReasoning,false);
        tutorDocumentConnection.addComponentListener(new java.awt.event.ComponentAdapter(){public void componentResized(java.awt.event.ComponentEvent e){updateTutorConnection();}});
        showTab("요약");
        addHierarchyListener(event->{
            if((event.getChangeFlags()&HierarchyEvent.SHOWING_CHANGED)!=0&&isShowing())studyViewsWereVisible=true;
        });
        for(JComponent studyView:List.of(summaryScroll,conceptOverview))studyView.addHierarchyListener(event->{
            if((event.getChangeFlags()&HierarchyEvent.SHOWING_CHANGED)!=0&&studyView.isShowing())
                SwingUtilities.invokeLater(this::refreshPendingStudyViews);
        });
        setControls();
        installDropTargets(this);
        installDropTargets(rightContent);
        unwatchTutor=dev.synesis.poc.ui.AnimationWindow.watch(tutorPanel,this::syncTutorAnimations);
    }

    public void showSummary() { showTab("요약"); }
    public void showTutor() { showTab("AI멘토"); }
    public void showConceptSummary() { showTab("개념정리"); }

    /** Register an additional view in the study columns and their navigation. */
    public void addLearningTab(String name, JComponent content) {
        JPanel panel=new JPanel(new BorderLayout());panel.setOpaque(false);
        JPanel heading=MistWorkspaceTheme.heading(24);
        heading.add(studyColumns.selector(name,name),BorderLayout.CENTER);
        heading.add(PanelCloseButtons.close(name+" 창 닫기",()->closeLearningTab(name)),BorderLayout.EAST);
        panel.add(heading,BorderLayout.NORTH);panel.add(content,BorderLayout.CENTER);
        studyColumns.register(name,name,panel);
        JToggleButton button=new TabButton(name);learningTabs.add(button);tabButtons.put(name,button);learningNavigationTabs.add(button);
        button.addActionListener(e->studyColumns.openFromNavigation(name));
        updateNavigationAddMarkers();
    }

    public void showLearningTab(String name) { showTab(name); }
    public void applyStudyFonts(StudyFontSettings previous, StudyFontSettings current) {
        if (previous.summaryFont() != current.summaryFont()) summaryFontSize.setValue(current.summaryFont());
        if (previous.tutorFont() != current.tutorFont()) tutorFontSize.setValue(current.tutorFont());
    }
    public void applyDisplaySettings(DisplaySettings settings) {
        summaryFontSize.setValue(settings.summaryFont());
        conceptFontSize.setValue(settings.conceptFont());
        tutorFontSize.setValue(settings.tutorFont());
        quiz.setQuestionFont(settings.quizFont());
        if(!pdfQuality.equals(settings.pdfQuality())) {
            pdfQuality=settings.pdfQuality();
            if(source!=null)renderPage(captureZoomAnchor(null,null));
        }
    }

    public JPanel moveLearningNavigation() {
        dropContent.remove(learningNavigation);
        learningNavigation.setBorder(null);
        dropContent.revalidate();
        return learningNavigation;
    }

    /** Controls and status for the currently displayed document. The host may move this panel to its header. */
    public JPanel studyActions() { return studyActions; }

    public void closeOriginalOnlyView() { leavePdfOnly(); }

    /** Whether this document should remain alive when the host switches to another PDF. Call on the EDT. */
    public boolean hasActiveStudyWork() {
        return !closed && (busy || tutorBusy || hasBackgroundQuizGeneration() || externalBatchActive
            || generationProgress != null && !generationProgress.finished());
    }

    public JToggleButton movePdfToggle(){
        if(pdfToggle.getParent()!=null)pdfToggle.getParent().remove(pdfToggle);
        return pdfToggle;
    }

    public void setPdfOnlyScreenHandler(Consumer<JComponent> opener,Runnable back){pdfOnlyOpener=opener;pdfOnlyReturn=back;}
    private void toggleQuizMaximize(){
        if(pdfVisible){
            quizExpansionCycle=true;
            setPdfVisible(false);
            quiz.setMaximizeAction("이전 패널 상태로 돌아가기");
        } else if(quizExpansionCycle){
            quizExpansionCycle=false;
            setPdfVisible(true);
            quiz.setMaximizeAction("PDF 접기");
        }
    }

    private void showPdfOnly(){
        if(source==null||pdfOnlyScreen!=null)return;
        // Keep the selected slide centered after the full-view viewport has its final size.
        ZoomAnchor anchor=new ZoomAnchor(page,.5,.5,-1,-1);
        pendingLayoutAnchor=anchor;
        scrollPageTimer.stop();
        zoomWheelAccumulation=0;
        sourceTabs.setSelectedIndex(0);
        sourceTabs.setComponentAt(0,new JPanel());
        JPanel screen=new LayoutMotionPanel(new BorderLayout());screen.setBackground(Color.WHITE);pdfOnlyScreen=screen;
        JPanel bar=new JPanel(new GridLayout(1,3,12,0));bar.setBackground(Color.WHITE);bar.setBorder(new EmptyBorder(8,16,8,16));
        JButton back=new JButton("돌아가기",MistWorkspaceTheme.icon("back",16));MistWorkspaceTheme.button(back,true);
        back.addActionListener(e->leavePdfOnly());
        JPanel backTools=new JPanel(new FlowLayout(FlowLayout.LEFT,8,0));backTools.setOpaque(false);backTools.add(back);backTools.add(thumbnailToggle);bar.add(backTools);
        JPanel pageTools=new JPanel(new FlowLayout(FlowLayout.CENTER,0,0));pageTools.setOpaque(false);
        // Share the existing controls so scroll updates and typed navigation need no second page model.
        pageTools.add(pdfPageNavigation);bar.add(pageTools);
        JButton minus=MistWorkspaceTheme.iconButton("minus","축소",16),plus=MistWorkspaceTheme.iconButton("plus","확대",16);
        minus.addActionListener(e->changePdfZoom(-1,null,null));
        plus.addActionListener(e->changePdfZoom(1,null,null));
        JPanel tools=new JPanel(new FlowLayout(FlowLayout.RIGHT,4,0));tools.setOpaque(false);tools.add(minus);tools.add(fullZoom);tools.add(plus);bar.add(tools);
        screen.add(bar,BorderLayout.NORTH);screen.add(pdfReadingArea,BorderLayout.CENTER);pdfReadingArea.setVisible(true);
        screen.getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW).put(KeyStroke.getKeyStroke(KeyEvent.VK_ESCAPE,0),"back");
        screen.getActionMap().put("back",new AbstractAction(){public void actionPerformed(java.awt.event.ActionEvent e){leavePdfOnly();}});
        if(pdfOnlyOpener!=null)pdfOnlyOpener.accept(screen);
        else {
            JDialog dialog=new JDialog(SwingUtilities.getWindowAncestor(this),"PDF 전체보기",Dialog.ModalityType.MODELESS);
            dialog.setContentPane(screen);dialog.setSize(1100,850);dialog.setLocationRelativeTo(this);
            dialog.addWindowListener(new java.awt.event.WindowAdapter(){public void windowClosing(java.awt.event.WindowEvent e){leavePdfOnly();}});
            screen.putClientProperty("synesis.pdfOnlyDialog",dialog);dialog.setVisible(true);
        }
        SwingUtilities.invokeLater(()->renderPage(anchor));
    }

    private void leavePdfOnly(){
        if(pdfOnlyScreen==null)return;
        ZoomAnchor anchor=captureZoomAnchor(null,null);JPanel screen=pdfOnlyScreen;pdfOnlyScreen=null;
        zoomWheelAccumulation=0;
        pdfNavigation.add(pdfPageNavigation,0);pdfNavigation.add(thumbnailToggle,0);pdfNavigation.revalidate();
        screen.remove(pdfReadingArea);sourceTabs.setComponentAt(0,pdfReadingArea);sourceTabs.setSelectedIndex(0);pdfReadingArea.setVisible(true);
        if(screen.getClientProperty("synesis.pdfOnlyDialog") instanceof JDialog dialog)dialog.dispose();
        else if(pdfOnlyReturn!=null)pdfOnlyReturn.run();
        revalidate();SwingUtilities.invokeLater(()->renderPage(anchor));
    }

    public JPanel moveTutorToSidePanel(Runnable opener,Runnable closer) {
        tutorSideCloser=Objects.requireNonNull(closer);
        return moveTutorToSidePanel(opener);
    }

    public JPanel moveTutorToSidePanel(Runnable opener) {
        tutorSideOpener=Objects.requireNonNull(opener);
        JToggleButton tab=tabButtons.remove("AI멘토");
        if(tab==null) {
            if(tutorPanel.getParent()!=null)tutorPanel.getParent().remove(tutorPanel);
            tutorPanel.setVisible(true);
            return tutorPanel;
        }
        learningTabs.remove(tab);
        if(tab.getParent()!=null)tab.getParent().remove(tab);
        rightContent.remove(tutorPanel);
        // CardLayout hid this card while the summary tab was selected. A moved
        // component keeps that visibility state until it is shown explicitly.
        tutorPanel.setVisible(true);
        showTab("요약");
        learningNavigation.revalidate();
        learningNavigation.repaint();
        return tutorPanel;
    }

    private void setPdfVisible(boolean visible) {
        if(visible==pdfVisible)return;
        if(!visible) {
            if(source!=null && sourceTabs.getSelectedIndex()==0)
                hiddenPdfAnchor=centeredPdfPageAnchor();
            rememberStudyDivider();
        }
        pdfVisible=visible;
        if(visible && hiddenPdfAnchor!=null)pendingLayoutAnchor=hiddenPdfAnchor;
        pdfToggle.setSelected(visible);
        updateStudyPanels();
        if(visible)SwingUtilities.invokeLater(()->{
            if(!pdfVisible)return;
            renderPage(hiddenPdfAnchor);
            hiddenPdfAnchor=null;
        });
    }

    private void closeLearningTab(String name) {
        studyColumns.closeView(name);
    }

    private void setLearningVisible(boolean visible) {
        if(visible==learningVisible)return;
        preservePdfPageForPanelLayout();
        if(!visible)rememberStudyDivider();
        learningVisible=visible;
        if(!visible)learningTabs.clearSelection();
        updateStudyPanels();
    }

    private void rememberStudyDivider() {
        if(!pdfVisible || !learningVisible)return;
        int divider=sidePanelVisible?dividerBeforeSidePanel:studySplit.getDividerLocation();
        if(divider>0)dividerBeforePdfHide=divider;
    }

    private void updateStudyPanels() {
        if(studyTransition!=null) {studyTransition.stop();studyTransition=null;}
        if(LayoutMotionPanel.isImmediateLayout() || !isShowing() || studySplit.getWidth()<=0) {
            applyStudyPanels();
            return;
        }
        int fullWidth=Math.max(0,studySplit.getWidth()-1);
        Component oldLeft=studySplit.getLeftComponent(),oldRight=studySplit.getRightComponent();
        int start=oldLeft==viewer && oldRight==learningPanel
            ?studySplit.getDividerLocation():oldLeft==viewer?fullWidth
            :oldRight==learningPanel?0:learningVisible?fullWidth:0;
        int target=pdfVisible && learningVisible
            ?Math.max(0,Math.min(fullWidth,sidePanelVisible
                ?fullWidth/2:restoredPdfDivider(Math.max(0,fullWidth-3))))
            :pdfVisible?fullWidth:learningVisible?0:oldRight==learningPanel?fullWidth:0;
        Component left=pdfVisible || oldLeft==viewer?viewer:emptyStudy;
        Component right=learningVisible || oldRight==learningPanel?learningPanel:emptyStudy;
        if(left==right) {
            applyStudyPanels();
            return;
        }
        viewer.setMinimumSize(new Dimension(0,0));
        learningPanel.setMinimumSize(new Dimension(0,0));
        studySplit.setLeftComponent(null);
        studySplit.setRightComponent(null);
        studySplit.setLeftComponent(left);
        studySplit.setRightComponent(right);
        studySplit.setDividerSize(4);
        studySplit.revalidate();
        studySplit.setDividerLocation(start);
        studyTransition=dev.synesis.poc.ui.SplitPaneTransition.animate(studySplit,target,100,()->{},()->{
                studyTransition=null;
                applyStudyPanels();
        });
    }

    private void applyStudyPanels() {
        Component left=pdfVisible?viewer:null;
        Component right=learningVisible?learningPanel:(pdfVisible?null:emptyStudy);
        if(studySplit.getLeftComponent()!=left)studySplit.setLeftComponent(left);
        if(studySplit.getRightComponent()!=right)studySplit.setRightComponent(right);
        studySplit.setDividerSize(pdfVisible && learningVisible?4:0);
        viewer.setMinimumSize(new Dimension(300,100));
        learningPanel.setMinimumSize(new Dimension(340,100));
        emptyStudyMessage.setText(sidePanelVisible
            ?"PDF 보기나 학습 탭을 열어보세요.":"열린 창이 아무것도 없어요. 고요하네요.");
        studySplit.revalidate();
        studySplit.repaint();
        if(pdfVisible && learningVisible) {
            Runnable layout=()->{
                if(studyTransition!=null || !pdfVisible || !learningVisible)return;
                if(sidePanelVisible)adjustSplitForSidePanel();
                else {
                    int available=studySplit.getWidth()-studySplit.getDividerSize();
                    if(available>0)studySplit.setDividerLocation(restoredPdfDivider(available));
                }
            };
            if(LayoutMotionPanel.isImmediateLayout())layout.run();
            else SwingUtilities.invokeLater(layout);
        }
    }

    private int restoredPdfDivider(int available) {
        int target=dividerBeforePdfHide>=0?dividerBeforePdfHide:(int)Math.round(available*INITIAL_PDF_RATIO);
        return available>=640?Math.max(300,Math.min(target,available-340)):Math.min(target,available);
    }

    public void setSidePanelVisible(boolean visible) {
        setSidePanelVisible(visible,true);
    }

    public void setSidePanelVisible(boolean visible,boolean animated) {
        if(visible==sidePanelVisible)return;
        preservePdfPageForPanelLayout();
        if(visible && pdfVisible && learningVisible)dividerBeforeSidePanel=studySplit.getDividerLocation();
        sidePanelVisible=visible;
        emptyStudyMessage.setText(visible
            ?"PDF 보기나 학습 탭을 열어보세요.":"열린 창이 아무것도 없어요. 고요하네요.");
        if(sideStudyTransition!=null) {sideStudyTransition.stop();sideStudyTransition=null;}
        if(!pdfVisible || !learningVisible)return;
        if(!animated || !isShowing() || studySplit.getWidth()<=0) {
            if(visible)adjustSplitForSidePanel();
            else studySplit.setDividerLocation(dividerBeforeSidePanel);
            return;
        }
            int available=Math.max(0,studySplit.getWidth()-studySplit.getDividerSize());
            int target=sidePanelVisible?defaultSidePanelDivider(available)
                :Math.max(300,Math.min(dividerBeforeSidePanel,available-340));
        sideStudyTransition=dev.synesis.poc.ui.SplitPaneTransition.animate(studySplit,target,100,()->{},()->{
                sideStudyTransition=null;
        });
    }

    private void adjustSplitForSidePanel() {
        if(studyTransition!=null || sideStudyTransition!=null || !pdfVisible || !learningVisible)return;
        int available=studySplit.getWidth()-studySplit.getDividerSize();
        if(available>0)studySplit.setDividerLocation(defaultSidePanelDivider(available));
    }

    private static int defaultSidePanelDivider(int available) {
        // Figma Mist navy: 496px PDF / 648px summary, without constraining later manual resizing.
        return Math.max(300,Math.min(available-340,(int)Math.round(available*(496d/1144))));
    }

    public void refreshSidePanelLayout() {
        if(sidePanelVisible)adjustSplitForSidePanel();
    }

    /** Called once after the outer pane's final width is committed. */
    public void settleSidePanelLayout() {
        if(sidePanelVisible)adjustSplitForSidePanel();
        else if(pdfVisible&&learningVisible) {
            int available=studySplit.getWidth()-studySplit.getDividerSize();
            studySplit.setDividerLocation(Math.max(300,Math.min(dividerBeforeSidePanel,available-340)));
        }
    }

    private static ExecutorService executor(String name) {
        return Executors.newSingleThreadExecutor(task -> { Thread t = new Thread(task, name); t.setDaemon(true); return t; });
    }

    private void buildViewer() {
        viewer.setBorder(new EmptyBorder(1,1,1,1));
        JPanel top = new JPanel(new BorderLayout());top.setOpaque(false);
        JPanel titleRow=MistWorkspaceTheme.heading(20);
        JLabel sourceTitle=MistWorkspaceTheme.label("PDF 원문",14,MistWorkspaceTheme.INK,Font.PLAIN);
        sourceTitle.setIcon(MistWorkspaceTheme.icon("file",18));sourceTitle.setIconTextGap(8);titleRow.add(sourceTitle,BorderLayout.WEST);
        JButton open = new JButton("PDF 불러오기"); open.addActionListener(e -> choosePdf());
        JButton find = new JButton("원문 검색"); find.addActionListener(e -> { searchPanel.setVisible(!searchPanel.isVisible()); viewer.revalidate(); search.requestFocusInWindow(); });
        JPanel navigation = row();
        pdfNavigation=navigation;
        ((FlowLayout)navigation.getLayout()).setHgap(4);
        thumbnailToggle.setPreferredSize(new Dimension(28,28));
        thumbnailToggle.getAccessibleContext().setAccessibleName("페이지 목록");
        thumbnailToggle.addActionListener(e->{
            boolean showThumbnails=!thumbnailScroll.isVisible();
            if(showThumbnails)sourceTabs.setSelectedIndex(0);
            thumbnailScroll.setVisible(showThumbnails);thumbnailToggle.setSelected(showThumbnails);
            thumbnailToggle.setToolTipText(showThumbnails?"페이지 목록 닫기":"페이지 목록 열기");
            pdfReadingArea.revalidate();
            if(source!=null) SwingUtilities.invokeLater(this::renderPage);
        });
        JButton prev = MistWorkspaceTheme.iconButton("previous","이전 페이지",16), next = MistWorkspaceTheme.iconButton("next","다음 페이지",16);
        prev.addActionListener(e -> showPage(page-1)); next.addActionListener(e -> showPage(page+1));
        prev.setPreferredSize(new Dimension(28,28));next.setPreferredSize(new Dimension(28,28));
        pageNumber.setUI(new javax.swing.plaf.basic.BasicSpinnerUI(){
            @Override protected Component createNextButton(){return null;}
            @Override protected Component createPreviousButton(){return null;}
        });
        pageNumber.setPreferredSize(new Dimension(28,28));pageNumber.setBorder(null);pageNumber.setOpaque(false);
        if(pageNumber.getEditor() instanceof JSpinner.DefaultEditor editor){editor.setOpaque(false);editor.getTextField().setUI(new javax.swing.plaf.basic.BasicTextFieldUI());editor.getTextField().setOpaque(false);editor.getTextField().setBorder(null);editor.getTextField().setHorizontalAlignment(SwingConstants.CENTER);}
        JPanel currentPageField=new MistWorkspaceTheme.Panel(new BorderLayout(),6,MistWorkspaceTheme.SOFT,null);
        currentPageField.putClientProperty("mist.shadow",null);currentPageField.setPreferredSize(new Dimension(28,28));currentPageField.add(pageNumber);
        pageNumber.addChangeListener(e -> { if (source != null && ((Number)pageNumber.getValue()).intValue()!=page) showPage(((Number)pageNumber.getValue()).intValue()); });
        pdfPageNavigation.setOpaque(false);
        pdfPageNavigation.add(prev);pdfPageNavigation.add(currentPageField);pdfPageNavigation.add(pageLabel);pdfPageNavigation.add(next);
        navigation.add(thumbnailToggle);navigation.add(pdfPageNavigation);navigation.add(Box.createHorizontalStrut(8));
        zoomOut.setToolTipText("PDF 축소 (Ctrl+마우스 휠 아래)");
        zoomIn.setToolTipText("PDF 확대 (Ctrl+마우스 휠 위)");
        zoomOut.addActionListener(e -> changePdfZoom(-1,null,null));
        zoomIn.addActionListener(e -> changePdfZoom(1,null,null));
        zoom.setPreferredSize(new Dimension(112,34));
        zoomOut.setText("");zoomOut.setIcon(MistWorkspaceTheme.icon("minus",16));MistWorkspaceTheme.button(zoomOut,false);zoomOut.setPreferredSize(new Dimension(28,28));
        zoomIn.setText("");zoomIn.setIcon(MistWorkspaceTheme.icon("plus",16));MistWorkspaceTheme.button(zoomIn,false);zoomIn.setPreferredSize(new Dimension(28,28));
        navigation.add(zoomOut); navigation.add(zoom); navigation.add(zoomIn);
        visual.setToolTipText("페이지 전체의 글자·수식·도표를 함께 분석합니다.");
        visual.addActionListener(e -> analyzeVisiblePage());
        zoom.addActionListener(e->pdfZoomChanged(zoom));
        fullZoom.addActionListener(e->pdfZoomChanged(fullZoom));
        fullZoom.setPreferredSize(new Dimension(120,32));
        MistWorkspaceTheme.comboBox(fullZoom,true);
        JScrollPane navigationScroll=new SmoothScrollPane(navigation,
            JScrollPane.VERTICAL_SCROLLBAR_NEVER,JScrollPane.HORIZONTAL_SCROLLBAR_AS_NEEDED);
        navigationScroll.setBorder(null);
        navigationScroll.setPreferredSize(new Dimension(100,47));
        JPanel readingTools=new JPanel(new BorderLayout());readingTools.setBackground(Color.WHITE);readingTools.setBorder(new EmptyBorder(0,8,0,12));
        JPanel readingActions=new JPanel(new FlowLayout(FlowLayout.RIGHT,4,7));readingActions.setOpaque(false);
        readingActions.add(expandPdf);
        readingTools.add(navigationScroll,BorderLayout.CENTER);readingTools.add(readingActions,BorderLayout.EAST);
        expandPdf.addActionListener(e->showPdfOnly());
        top.add(readingTools,BorderLayout.CENTER);
        analyzeImages.setToolTipText("이미지의 학습상 역할을 판단해 필요한 설명을 저장합니다. 완료된 결과는 재사용합니다.");
        analyzeImages.addActionListener(e -> prepareImageAnalysis());
        imageReport.addActionListener(e -> showImageAssessmentReport());
        JButton more=MistWorkspaceTheme.iconButton("dots","PDF 도구",16);
        JPopupMenu tools=new JPopupMenu();
        JMenuItem showPdf=new JMenuItem("PDF 보기"),showOriginal=new JMenuItem("추출 원문 보기");
        showPdf.addActionListener(e->sourceTabs.setSelectedIndex(0));showOriginal.addActionListener(e->sourceTabs.setSelectedIndex(1));
        tools.add(showPdf);tools.add(showOriginal);tools.addSeparator();
        for(JButton action:new JButton[]{open,find,visual,analyzeImages,imageReport})addToolMenuItem(tools,action);
        more.addActionListener(e->tools.show(more,0,more.getHeight()));
        readingActions.add(more,0);
        JButton closePdf=PanelCloseButtons.close("PDF 원문 창 닫기",()->setPdfVisible(false));
        JPanel titleTools=new JPanel(new FlowLayout(FlowLayout.RIGHT,8,5));titleTools.setOpaque(false);titleTools.add(closePdf);
        titleRow.add(titleTools,BorderLayout.EAST);top.add(titleRow,BorderLayout.NORTH);
        viewer.add(top, BorderLayout.NORTH);
        imageCanvas.setBackground(Color.WHITE); imageCanvas.add(pageImage);
        imageCanvas.setFocusable(true);
        imageCanvas.addMouseWheelListener(event -> {
            Point point=SwingUtilities.convertPoint(imageCanvas,event.getPoint(),imageScroll);
            imageScroll.dispatchEvent(new java.awt.event.MouseWheelEvent(imageScroll,event.getID(),
                event.getWhen(),event.getModifiersEx(),point.x,point.y,
                event.getXOnScreen(),event.getYOnScreen(),event.getClickCount(),event.isPopupTrigger(),
                event.getScrollType(),event.getScrollAmount(),event.getWheelRotation(),
                event.getPreciseWheelRotation()));
            event.consume();
        });
        imageCanvas.getInputMap(JComponent.WHEN_FOCUSED).put(KeyStroke.getKeyStroke("control C"), "copyPdfText");
        imageCanvas.getInputMap(JComponent.WHEN_FOCUSED).put(KeyStroke.getKeyStroke("meta C"), "copyPdfText");
        imageCanvas.getActionMap().put("copyPdfText", new AbstractAction() {
            @Override public void actionPerformed(java.awt.event.ActionEvent event) {copySelectedPdfText();}
        });
        imageCanvas.addMouseListener(new java.awt.event.MouseAdapter() {
            @Override public void mouseClicked(java.awt.event.MouseEvent e) {if(selectingImage)selectImageAt(e.getPoint());}
            @Override public void mousePressed(java.awt.event.MouseEvent e) {
                if(e.isPopupTrigger()){showPdfTextMenu(e);return;}
                if(selectingImage || index==null || !SwingUtilities.isLeftMouseButton(e))return;
                PageLayout layout=textPageAt(e.getPoint(),true);
                PdfTextSelection.Word word=layout==null?null:textSelection.hit(index,layout.number(),layout.bounds(),e.getPoint(),true);
                if(word==null)textSelection.clear();else {textSelection.press(word);imageCanvas.requestFocusInWindow();}
                imageCanvas.repaint();
            }
            @Override public void mouseReleased(java.awt.event.MouseEvent e) {
                if(!textSelection.hasSelection()) {textSelection.clear();imageCanvas.repaint();}
                if(e.isPopupTrigger())showPdfTextMenu(e);
            }
            @Override public void mouseExited(java.awt.event.MouseEvent e) {
                if(!selectingImage)imageCanvas.setCursor(Cursor.getDefaultCursor());
            }
        });
        imageCanvas.addMouseMotionListener(new java.awt.event.MouseMotionAdapter() {
            @Override public void mouseDragged(java.awt.event.MouseEvent e) {
                if(selectingImage || index==null || (e.getModifiersEx() & java.awt.event.InputEvent.BUTTON1_DOWN_MASK)==0)return;
                PageLayout layout=textPageAt(e.getPoint(),false);
                if(layout==null)return;
                PdfTextSelection.Word word=textSelection.hit(index,layout.number(),layout.bounds(),e.getPoint(),false);
                textSelection.drag(word);imageCanvas.repaint();
            }
            @Override public void mouseMoved(java.awt.event.MouseEvent e) {
                if(selectingImage || index==null)return;
                PageLayout layout=textPageAt(e.getPoint(),true);
                boolean overText=layout!=null && textSelection.hit(index,layout.number(),layout.bounds(),e.getPoint(),true)!=null;
                imageCanvas.setCursor(Cursor.getPredefinedCursor(overText?Cursor.TEXT_CURSOR:Cursor.DEFAULT_CURSOR));
            }
        });
        imageScroll.setBorder(null); imageScroll.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
        imageScroll.putClientProperty("synesis.resizeOwnAnchor",true);
        imageScroll.getViewport().addChangeListener(e->onPageViewportChanged());
        javax.swing.Timer resizeTimer=new javax.swing.Timer(40,e->{
            if(source==null)return;
            ZoomAnchor anchor=panelLayoutAnchor!=null?panelLayoutAnchor:pendingLayoutAnchor!=null?pendingLayoutAnchor:captureZoomAnchor(null,null);
            pendingLayoutAnchor=null;
            finishPdfResize(anchor);
        });
        resizeTimer.setRepeats(false);
        imageScroll.getViewport().addComponentListener(new java.awt.event.ComponentAdapter() {
            @Override public void componentResized(java.awt.event.ComponentEvent e){
                if(source==null)return;
                // Component resize notifications can arrive AFTER the final
                // render at those same bounds. Do not capture the top edge as
                // a new page anchor after restoring the requested page center.
                if(panelLayoutAnchor==null && pdfLayoutWidth()==lastViewportWidth
                        &&imageScroll.getViewport().getHeight()==lastViewportHeight)return;
                if(panelLayoutAnchor!=null){pendingLayoutAnchor=panelLayoutAnchor;if(!outerPanelLayoutChanging)panelAnchorTimer.restart();}
                if(pendingLayoutAnchor==null) {
                    Rectangle visible=imageScroll.getViewport().getViewRect();
                    pendingLayoutAnchor=captureZoomAnchor(new Point(visible.x+visible.width/2,visible.y+2),new Point(visible.width/2,2));
                }
                if("너비 맞춤".equals(activePdfZoom().getSelectedItem()))
                    previewPdfResize(pendingLayoutAnchor!=null?pendingLayoutAnchor:captureZoomAnchor(null,null));
                resizeTimer.restart();
            }
        });
        thumbnailCanvas.setBackground(MistWorkspaceTheme.SOFT);
        thumbnailCanvas.addMouseListener(new java.awt.event.MouseAdapter() {
            @Override public void mouseClicked(java.awt.event.MouseEvent e){
                if(thumbnailLayouts.isEmpty() || e.getY()<0 || e.getY()>=thumbnailCanvas.getPreferredSize().height)return;
                int selected=thumbnailPageAt(e.getY());
                if(source!=null && selected<=source.count) showPage(selected);
            }
        });
        thumbnailScroll.setPreferredSize(new Dimension(170,300));
        thumbnailScroll.setBorder(BorderFactory.createMatteBorder(0,0,0,1,new Color(0xd8e5f5)));
        thumbnailScroll.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
        thumbnailScroll.getViewport().addChangeListener(e->refreshThumbnails());
        thumbnailScroll.setVisible(false);
        JPanel pdfView=new JPanel(new BorderLayout());pdfView.add(thumbnailScroll,BorderLayout.WEST);pdfView.add(imageScroll,BorderLayout.CENTER);pdfReadingArea=pdfView;
        sourceTabs.addTab("PDF", pdfView); sourceTabs.addTab("추출 원문", originalScroll);
        sourceTabs.setUI(new javax.swing.plaf.basic.BasicTabbedPaneUI(){
            @Override protected int calculateTabAreaHeight(int placement,int runs,int height){return 0;}
            @Override protected int calculateTabAreaWidth(int placement,int runs,int width){return 0;}
            @Override protected Insets getContentBorderInsets(int placement){return new Insets(0,0,0,0);}
            @Override protected void paintTabArea(Graphics g,int placement,int selected){}
        });
        sourceTabs.addChangeListener(event->{
            if(sourceTabs.getSelectedIndex()==1) {
                originalScroll.setViewportView(original);
                if(originalDirty)updateOriginal();
                else originalScroll.getViewport().setViewPosition(originalScrollPosition);
            } else {
                originalScrollPosition=originalScroll.getViewport().getViewPosition();
                // Swing validates hidden tab contents too. Detach the inactive
                // text view so raw PDF glyphs never reflow behind the PDF canvas.
                originalScroll.setViewportView(null);
            }
        });
        viewer.add(sourceTabs, BorderLayout.CENTER);
        searchPanel.setBorder(new EmptyBorder(8, 12, 8, 12));
        searchPanel.add(search, BorderLayout.NORTH);
        search.setToolTipText("검색어 입력 후 Enter"); search.addActionListener(e -> searchOriginal());
        searchResults.setCellRenderer((list, value, itemIndex, selected, focus) -> {
            JLabel label = new JLabel("p."+value.get("page").getAsInt()+"  "+str(value,"text").replaceAll("\\s+"," "));
            label.setBorder(new EmptyBorder(5,5,5,5)); label.setOpaque(true);
            label.setBackground(selected?StudyTheme.ACCENT_SOFT:Color.WHITE); return label;
        });
        searchResults.addListSelectionListener(e -> {
            if (!e.getValueIsAdjusting() && searchResults.getSelectedValue()!=null) {
                JsonObject hit = searchResults.getSelectedValue(); showPage(hit.get("page").getAsInt());
                sourceTabs.setSelectedIndex(1);
                original.setText(documentHtml("원문 위치", "<p>"+escape(str(hit,"source"))+" · PDF "+hit.get("page").getAsInt()+"쪽</p><blockquote>"+escape(str(hit,"text"))+"</blockquote>"));
            }
        });
        JScrollPane resultScroll = new SmoothScrollPane(searchResults); resultScroll.setPreferredSize(new Dimension(100, 120));
        searchPanel.add(resultScroll, BorderLayout.CENTER); searchPanel.setVisible(false);
        viewer.add(searchPanel, BorderLayout.SOUTH);
        original.addHyperlinkListener(e -> { if(e.getEventType()==javax.swing.event.HyperlinkEvent.EventType.ACTIVATED) navigate(e.getDescription()); });
    }

    private static void addToolMenuItem(JPopupMenu menu,JButton action){
        JMenuItem item=new JMenuItem(action.getText());item.addActionListener(e->action.doClick());menu.add(item);
        menu.addPopupMenuListener(new javax.swing.event.PopupMenuListener(){
            public void popupMenuWillBecomeVisible(javax.swing.event.PopupMenuEvent e){
                item.setText(action.getText());item.setEnabled(action.isEnabled());item.setVisible(action.isVisible());
            }
            public void popupMenuWillBecomeInvisible(javax.swing.event.PopupMenuEvent e){}
            public void popupMenuCanceled(javax.swing.event.PopupMenuEvent e){}
        });
    }

    private void buildStudyActions() {
        studyActions.setBackground(Color.WHITE);
        studyActions.setBorder(new EmptyBorder(5, 12, 5, 12));
        JPanel controls = new JPanel(new FlowLayout(FlowLayout.LEFT, 6, 0));
        controls.setOpaque(false);
        studyScope.getAccessibleContext().setAccessibleName("해설 범위");
        studyScope.setToolTipText("강의 해설 생성 범위");
        studyScope.setPreferredSize(new Dimension(126, 32));
        summaryStrategy.getAccessibleContext().setAccessibleName("해설 생성 방식");
        summaryStrategy.setToolTipText("기존 결과와 새 결과를 별도로 보관해 언제든 전환할 수 있어요.");
        summaryStrategy.setPreferredSize(new Dimension(224, 32));
        StudyTheme.comboBox(studyScope);
        StudyTheme.comboBox(summaryStrategy);
        summaryStrategy.setSelectedIndex(Arrays.asList(STRATEGY_IDS).indexOf(PdfStudyStrategy.DEFAULT));
        scope.addActionListener(e -> {
            selectProduct(); renderSummary(); if(generated!=null)fadeInSavedSummary(); showConcepts(); setControls();
        });
        summaryStrategy.addActionListener(e -> {
            generationEngineSelected=true; clearLiveSummary(); selectProduct(); renderSummary();
            if(generated!=null)fadeInSavedSummary(); showConcepts(); setControls();
        });
        generate.addActionListener(e -> {
            // The independent window already exposes the selected engine beside the button.
            generationEngineSelected=true;
            startGeneration();
        });
        regenerate.addActionListener(e -> {
            generationEngineSelected=true;
            startGeneration(0,true);
        });
        comparisonResults.addActionListener(e -> showComparisonDialog());
        strategyComparison.addActionListener(e -> showStrategyComparison());
        semanticCoverage.addActionListener(e -> showSemanticCoverage());
        cancel.addActionListener(e -> cancelAnalysis());
        retry.addActionListener(e -> prepare(true));

        JButton toolsButton = new JButton("해설 도구");
        JPopupMenu tools = new JPopupMenu();
        for (JButton action : new JButton[]{regenerate, semanticCoverage, strategyComparison, comparisonResults}) {
            addToolMenuItem(tools, action);
        }
        toolsButton.addActionListener(e -> tools.show(toolsButton, 0, toolsButton.getHeight()));
        controls.add(studyScope);
        controls.add(summaryStrategy);
        controls.add(generate);
        controls.add(toolsButton);
        recoveryRow.setOpaque(false);
        ((FlowLayout)recoveryRow.getLayout()).setVgap(0);
        recoveryRow.add(cancel);
        recoveryRow.add(retry);
        controls.add(recoveryRow);
        JScrollPane scroll = new SmoothScrollPane(controls,
            JScrollPane.VERTICAL_SCROLLBAR_NEVER, JScrollPane.HORIZONTAL_SCROLLBAR_AS_NEEDED);
        scroll.setPreferredSize(new Dimension(300, 46));
        studyActions.add(scroll, BorderLayout.CENTER);
        status.setForeground(MUTED);
        status.setFont(StudyTheme.font(Font.PLAIN, 12));
        status.setBorder(new EmptyBorder(1, 6, 3, 6));
        studyActions.add(status, BorderLayout.SOUTH);
        styleControls(studyActions);
    }

    private JPanel buildLearning() {
        JPanel right = new LayoutMotionPanel(new BorderLayout(),12,Color.WHITE,MistWorkspaceTheme.LINE);
        right.setBackground(Color.WHITE);right.setBorder(new EmptyBorder(1,1,1,1));
        JPanel tabs = learningNavigationTabs;
        pdfToggle=new JToggleButton("PDF 보기");
        pdfToggle.setSelected(true);
        MistWorkspaceTheme.button(pdfToggle,true);
        Insets pdfInsets=pdfToggle.getInsets();
        int pdfButtonWidth=pdfToggle.getFontMetrics(pdfToggle.getFont()).stringWidth(pdfToggle.getText())+pdfInsets.left+pdfInsets.right+8;
        Dimension pdfButtonSize=new Dimension(Math.max(84,pdfButtonWidth),34);
        pdfToggle.setPreferredSize(pdfButtonSize);pdfToggle.setMinimumSize(pdfButtonSize);
        pdfToggle.addActionListener(e -> {
            setPdfVisible(pdfToggle.isSelected());
        });

        // Keep navigation keys stable; only the visible product names change.
        String[] names = {"요약", "개념정리", "AI멘토", "퀴즈로 학습하기"};
        for (String name:names) {
            String display=switch(name) {
                case "요약" -> "강의 해설";
                case "개념정리" -> "개념 정리";
                case "퀴즈로 학습하기" -> "N제 출제";
                default -> name;
            };
            JToggleButton button = new TabButton(display); learningTabs.add(button); if(!name.equals("AI멘토"))tabs.add(button);tabButtons.put(name,button);
            button.addActionListener(e -> {
                studyColumns.openFromNavigation(name);
            });
            if(name.equals("요약")) button.setSelected(true);
        }
        learningNavigation.setBackground(Color.WHITE);
        learningNavigation.add(tabs,BorderLayout.CENTER);
        rightContent.setBackground(Color.WHITE);
        rightContent.add(quiz, "퀴즈로 학습하기");
        JPanel summaryPanel = new JPanel(new BorderLayout()); summaryPanel.setBackground(Color.WHITE);
        JPanel summaryTop=new JPanel(new BorderLayout());summaryTop.setOpaque(false);
        JButton textSize=new JButton("Aa · 글자 크기 조절");MistWorkspaceTheme.button(textSize,false);
        textSize.addActionListener(e->MistWorkspaceTheme.textSizeDialog(this,summaryFontSize,"강의 해설 글자 크기",false,"px"));
        JButton summaryClose=PanelCloseButtons.close("강의 해설 창 닫기",()->closeLearningTab("요약"));
        JPanel summaryHeading=new SummaryHeader(textSize,summaryClose,studyColumns.selector("요약","강의 해설"));
        summaryTop.add(summaryHeading,BorderLayout.NORTH);
        JPanel summaryNavigation=new JPanel(new BorderLayout(12,0));summaryNavigation.setBackground(Color.WHITE);summaryNavigation.setBorder(new EmptyBorder(8,24,8,12));
        JPanel summaryNavigationLeft=new JPanel(new FlowLayout(FlowLayout.LEFT,12,0));summaryNavigationLeft.setOpaque(false);
        summaryNavigation.setPreferredSize(new Dimension(1,51));
        JButton currentPage=new JButton("현재 페이지로");MistWorkspaceTheme.button(currentPage,true);currentPage.addActionListener(e->scrollSummaryToCurrentPage());
        currentPage.setToolTipText("현재 PDF 쪽의 해설로 이동해요. 해당 쪽에 해설이 없으면 다음 해설로 이동해요.");
        MistWorkspaceTheme.button(summaryOutlineButton,false);summaryOutlineButton.setToolTipText("강의 해설 목차 · 제목을 누르면 해당 내용으로 이동해요.");
        summaryOutlineButton.setFont(MistWorkspaceTheme.font(Font.BOLD,14));
        summaryOutlineButton.setBackground(MistWorkspaceTheme.SOFT);
        summaryOutlineButton.putClientProperty("mist.whiteButton",true);
        summaryOutlineButton.setBorder(new EmptyBorder(0,18,0,18));
        summaryOutlineButton.setPreferredSize(new Dimension(76,35));
        configureSummaryOutline();
        summaryOutlineButton.addActionListener(e->summaryOutlineHover.explicitOpen());
        summaryNavigationLeft.add(currentPage);
        summaryNavigation.add(summaryNavigationLeft,BorderLayout.CENTER);
        summaryNavigation.add(summaryOutlineButton,BorderLayout.EAST);
        JLabel navigationHint=MistWorkspaceTheme.label("PDF에서 보고 있는 페이지로 스크롤해요.",12,MistWorkspaceTheme.MUTED,Font.PLAIN);
        summaryNavigationLeft.add(navigationHint);
        summaryNavigation.addComponentListener(new java.awt.event.ComponentAdapter(){
            @Override public void componentResized(java.awt.event.ComponentEvent e){navigationHint.setVisible(summaryNavigation.getWidth()>600);summaryOutlineTargets=Map.of();summaryOutlineOffsets.clear();}
        });
        summaryTop.add(summaryNavigation,BorderLayout.CENTER);
        if(automaticStudy) {
            automaticStudyStatus.setFont(StudyTheme.font(Font.PLAIN,12));
            automaticStudyStatus.setForeground(MUTED);
            automaticStudyStatus.setBorder(new EmptyBorder(0,24,8,12));
            automaticStudyStatus.setVisible(false);
            MistWorkspaceTheme.button(automaticStudyAction,false);
            automaticStudyAction.addActionListener(e->{
                if(busy)cancelAnalysis();
                else if(source!=null && summaryActivity.state()==SummaryActivityBar.State.STOPPED) {
                    automaticStudyError=null;
                    if(index==null)prepare(true);
                    else startAutomaticStudy(0,true);
                }
            });
            automaticStudyAction.setVisible(false);
            summaryNavigationLeft.add(automaticStudyAction,1);
            summaryTop.add(automaticStudyStatus,BorderLayout.SOUTH);
        }
        summaryPanel.add(summaryTop,BorderLayout.NORTH);
        summaryScroll.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
        summaryScroll.getViewport().addChangeListener(e->updateSummaryOutlineSelection());
        configureSummaryPane(summary);
        summaryScroll.getVerticalScrollBar().addMouseListener(new java.awt.event.MouseAdapter(){
            @Override public void mousePressed(java.awt.event.MouseEvent e){summaryScrollInteraction++;}
            @Override public void mouseReleased(java.awt.event.MouseEvent e){summaryScrollInteraction++;}
        });
        summaryScroll.getVerticalScrollBar().addAdjustmentListener(e->{
            if(e.getValueIsAdjusting()&&!restoringSummaryScroll)summaryScrollInteraction++;
        });
        summaryScroll.getVerticalScrollBar().addKeyListener(new java.awt.event.KeyAdapter(){
            @Override public void keyPressed(java.awt.event.KeyEvent e){summaryScrollInteraction++;}
        });
        summaryFadeLayer.addHierarchyListener(event -> {
            if((event.getChangeFlags() & HierarchyEvent.SHOWING_CHANGED)!=0 && summaryFadeLayer.isShowing())
                SwingUtilities.invokeLater(this::startPendingSavedSummaryFade);
        });
        summaryPanel.add(summaryFadeLayer, BorderLayout.CENTER);
        rightContent.add(summaryPanel, "요약");
        studyColumns.register("요약","강의 해설",summaryPanel);
        summaryFontSize.addChangeListener(e -> {
            summaryFontValue.setText(summaryFontSize.getValue()+"px");
            if(!summaryFontSize.getValueIsAdjusting()) renderSummary(true);
        });
        JButton conceptClose=PanelCloseButtons.close("개념 정리 창 닫기",()->closeLearningTab("개념정리"));
        conceptOverview=new ConceptOverview(conceptList,conceptScroll,conceptFontSize,scope,conceptClose,studyColumns.selector("개념정리","개념 정리"));
        rightContent.add(conceptOverview, "개념정리");
        studyColumns.register("개념정리","개념 정리",conceptOverview);
        studyColumns.register("퀴즈로 학습하기","N제",quiz);
        quiz.setViewSelector(studyColumns.selector("퀴즈로 학습하기","N제"));
        conceptFontSize.addChangeListener(e -> {
            conceptFontValue.setText(conceptFontSize.getValue()+"pt");
            if(!conceptFontSize.getValueIsAdjusting()) showConcepts(true);
        });
        JPanel chat = new MistWorkspaceTheme.Panel(new BorderLayout(),12,Color.WHITE,MistWorkspaceTheme.LINE){
            // Composer height changes only invalidate this pane, not PDF/summary HTML layouts.
            @Override public boolean isValidateRoot(){return true;}
        };
        chat.putClientProperty("mist.smoothCorners",true);
        JPanel tutorTop=new JPanel(new BorderLayout());tutorTop.setOpaque(false);
        JPanel tutorHeading=MistWorkspaceTheme.heading(12);
        JButton closeTutor=PanelCloseButtons.collapseRight("AI멘토 창 닫기",()->{
            if(tutorSideCloser!=null)tutorSideCloser.run();else closeLearningTab("AI멘토");
        });
        JLabel tutorTitle=MistWorkspaceTheme.label("AI멘토",18,MistWorkspaceTheme.INK,Font.BOLD);
        JPanel tutorIdentity=new JPanel(null){
            @Override public void doLayout(){
                int height=getHeight(),width=getWidth();
                Dimension title=tutorTitle.getPreferredSize();
                closeTutor.setBounds(0,(height-32)/2,32,32);
                int titleX=44;
                tutorTitle.setBounds(titleX,(height-title.height)/2,Math.min(title.width,Math.max(0,width-titleX)),title.height);
            }
        };
        tutorIdentity.setOpaque(false);tutorIdentity.setMinimumSize(new Dimension(0,0));
        tutorIdentity.add(closeTutor);tutorIdentity.add(tutorTitle);
        tutorHeading.add(tutorIdentity,BorderLayout.CENTER);
        JButton tutorSettings=MistWorkspaceTheme.iconButton("settings","AI멘토 설정 · 글자 크기",16);
        tutorSettings.addActionListener(e->MistWorkspaceTheme.textSizeDialog(this,tutorFontSize,"AI멘토 설정",true,"px"));
        MistWorkspaceTheme.button(newChat,true);newChat.setIcon(MistWorkspaceTheme.icon("plus",12));
        newChat.setFont(MistWorkspaceTheme.font(Font.PLAIN,11));newChat.setBorder(new EmptyBorder(0,8,0,8));newChat.setPreferredSize(new Dimension(86,26));
        JPopupMenu tutorMenu=new JPopupMenu();addToolMenuItem(tutorMenu,newChat);tutorSettings.setComponentPopupMenu(tutorMenu);
        tutorHeading.add(tutorSettings,BorderLayout.EAST);tutorTop.add(tutorHeading,BorderLayout.NORTH);
        JPanel connectionRow=new JPanel(new FlowLayout(FlowLayout.LEFT,0,8));connectionRow.setBackground(Color.WHITE);connectionRow.setBorder(new EmptyBorder(0,20,0,20));connectionRow.setPreferredSize(new Dimension(1,43));
        tutorConnection.setBorder(new EmptyBorder(4,12,4,12));
        tutorConnection.setIcon(MistWorkspaceTheme.icon("file-small",12));tutorConnection.setIconTextGap(6);connectionRow.add(tutorConnection);
        connectionRow.add(Box.createHorizontalStrut(8));connectionRow.add(newChat);tutorTop.add(connectionRow,BorderLayout.CENTER);
        chat.add(tutorTop,BorderLayout.NORTH);
        chat.putClientProperty("synesis.floatingDragHandle",tutorIdentity);
        JPanel tutorWelcome = new JPanel(new GridBagLayout()); tutorWelcome.setBackground(Color.WHITE);
        JPanel welcomeContent = new JPanel(); welcomeContent.setOpaque(false);
        welcomeContent.setLayout(new BoxLayout(welcomeContent, BoxLayout.Y_AXIS));
        JLabel welcomeTitle = new JLabel("AI멘토에게 이 자료에 대해 물어보세요!", SwingConstants.CENTER);
        welcomeTitle.setFont(new Font(UiFonts.FAMILY, Font.BOLD, 21));
        welcomeTitle.putClientProperty("synesis.preserveFont",Boolean.TRUE);
        welcomeTitle.setAlignmentX(Component.CENTER_ALIGNMENT);
        welcomeContent.add(welcomeTitle); welcomeContent.add(Box.createVerticalStrut(25));
        JPanel suggestions = new JPanel(new GridLayout(1,3,12,0)); suggestions.setOpaque(false);
        for (TutorStarterPrompt prompt : TutorStarterPrompt.values()) {
            JButton suggestion = prompt.button(selected -> askTutor(selected.label(),new JsonObject(),page,selected));
            suggestions.add(suggestion);
        }
        int wideWelcomeWidth=suggestions.getPreferredSize().width+40;
        boolean[] compactWelcome={false};
        Runnable updateWelcomeLayout=()->{
            boolean compact=tutorWelcome.getWidth()<wideWelcomeWidth;
            if(compact==compactWelcome[0])return;
            compactWelcome[0]=compact;
            welcomeTitle.setText(compact
                ? "<html><div style='text-align:center'>AI멘토에게<br>이 자료에 대해 물어보세요!</div></html>"
                : "AI멘토에게 이 자료에 대해 물어보세요!");
            suggestions.setLayout(compact?new GridLayout(3,1,0,10):new GridLayout(1,3,12,0));
            welcomeContent.revalidate();
            tutorWelcome.revalidate();
            tutorWelcome.repaint();
        };
        tutorWelcome.addComponentListener(new java.awt.event.ComponentAdapter() {
            @Override public void componentResized(java.awt.event.ComponentEvent event) {updateWelcomeLayout.run();}
        });
        updateWelcomeLayout.run();
        welcomeContent.add(suggestions); tutorWelcome.add(welcomeContent);
        tutorBody.setBackground(Color.WHITE);
        tutorBody.add(tutorWelcome, "empty");
        tutorMessages.setBackground(Color.WHITE);
        tutorMessages.setLayout(new BoxLayout(tutorMessages,BoxLayout.Y_AXIS));
        tutorMessages.setBorder(new EmptyBorder(20,20,24,20));
        tutorScroll.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
        styleTutorScrollBars(tutorScroll);
        tutorBody.add(tutorScroll, "conversation");
        tutorScroll.getViewport().addComponentListener(new java.awt.event.ComponentAdapter() {
            @Override public void componentResized(java.awt.event.ComponentEvent event) {
                int width=tutorScroll.getViewport().getWidth();
                if(width==tutorViewportWidth)return;
                tutorViewportWidth=width;
                if(!conversation.isEmpty())scheduleTutorReflow();
            }
        });
        chat.add(tutorBody, BorderLayout.CENTER);
        tutorFontSize.addChangeListener(e -> {
            tutorFontValue.setText(tutorFontSize.getValue()+"px");
            if(!tutorFontSize.getValueIsAdjusting()) renderTutor(true);
        });
        JPanel composer = new JPanel(new BorderLayout(0,8));
        composer.setBackground(Color.WHITE);
        composer.setBorder(new EmptyBorder(12,16,16,16));
        question.setToolTipText("Enter 전송 · Shift+Enter 줄바꿈 · 이미지는 ⌘V/Ctrl+V로 붙여넣을 수 있어요");
        question.getAccessibleContext().setAccessibleName("AI멘토 질문 입력");
        question.getAccessibleContext().setAccessibleDescription("질문을 입력하고 Enter로 전송해요. Shift+Enter는 줄바꿈이에요.");
        search.getAccessibleContext().setAccessibleName("PDF 원문 검색어 입력");
        question.setUI(new javax.swing.plaf.basic.BasicTextAreaUI());
        question.setBorder(new EmptyBorder(2,8,2,8));question.setMargin(new Insets(0,0,0,0));
        question.setFont(MistWorkspaceTheme.font(Font.PLAIN,14));question.setForeground(MistWorkspaceTheme.TEXT);
        question.setRows(1); question.setColumns(16);
        question.setLineWrap(true); question.setWrapStyleWord(true);
        question.putClientProperty("synesis.preserveFont",Boolean.TRUE);
        installTutorPaste();
        tutorAttach.setToolTipText("AI멘토에 이미지 또는 4페이지 이하 PDF 첨부");
        tutorAttach.setText("");tutorAttach.setIcon(MistWorkspaceTheme.icon("attach",16));MistWorkspaceTheme.button(tutorAttach,false);tutorAttach.setPreferredSize(new Dimension(24,28));tutorAttach.setBorder(new EmptyBorder(0,0,0,0));
        tutorAttach.addActionListener(e -> chooseTutorAttachment());
        JScrollPane questionScroll = new dev.synesis.poc.ui.FadeScrollPane(question,
            JScrollPane.VERTICAL_SCROLLBAR_AS_NEEDED,JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
        questionScroll.setBorder(null); questionScroll.setOpaque(false);
        styleTutorScrollBars(questionScroll);
        questionScroll.getViewport().setOpaque(false);
        JPanel attachmentRow = new JPanel(new BorderLayout(0,4)); attachmentRow.setOpaque(false);
        JPanel attachmentHeading = row();attachmentHeading.setOpaque(false);
        tutorClearAttachment.setMargin(new Insets(0, 4, 0, 4));
        tutorClearAttachment.setToolTipText("첨부 모두 지우기");
        tutorClearAttachment.addActionListener(e -> clearTutorAttachments());
        attachmentHeading.add(tutorAttachmentLabel);attachmentHeading.add(tutorClearAttachment);
        attachmentRow.add(attachmentHeading,BorderLayout.NORTH);
        tutorAttachmentPreviews.setOpaque(false);
        JScrollPane previewScroll=new dev.synesis.poc.ui.FadeScrollPane(tutorAttachmentPreviews,
            JScrollPane.VERTICAL_SCROLLBAR_NEVER,JScrollPane.HORIZONTAL_SCROLLBAR_AS_NEEDED);
        previewScroll.setBorder(null);previewScroll.setOpaque(false);previewScroll.getViewport().setOpaque(false);
        styleTutorScrollBars(previewScroll);
        previewScroll.setPreferredSize(new Dimension(200,92));
        attachmentRow.add(previewScroll,BorderLayout.CENTER);
        attachmentRow.setVisible(false);
        tutorAttachmentLabel.putClientProperty("synesis.attachmentRow", attachmentRow);
        JPanel composerActions=new JPanel(new BorderLayout(6,0));composerActions.setOpaque(false);
        composerActions.add(tutorAttach,BorderLayout.WEST);composerActions.add(tutorDocumentConnection,BorderLayout.CENTER);
        ask.setText("");ask.setIcon(MistWorkspaceTheme.icon("send",16));MistWorkspaceTheme.button(ask,false);ask.setBackground(MistWorkspaceTheme.INK);ask.setPreferredSize(new Dimension(28,28));ask.setBorder(new EmptyBorder(0,0,0,0));
        ask.setUI(new javax.swing.plaf.basic.BasicButtonUI(){public void paint(Graphics graphics,JComponent component){Graphics2D g=(Graphics2D)graphics.create();try{g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setColor(MistWorkspaceTheme.INK);g.fillRoundRect(0,0,component.getWidth(),component.getHeight(),16,16);}finally{g.dispose();}super.paint(graphics,component);}});
        ask.setToolTipText("질문 보내기");ask.getAccessibleContext().setAccessibleName("질문 보내기");composerActions.add(ask,BorderLayout.EAST);
        tutorInputCard=new GrowingTutorInput(question,questionScroll,attachmentRow,composerActions);
        composer.add(tutorInputCard,BorderLayout.CENTER);
        JPanel buttons = row();buttons.setOpaque(false);
        FlowLayout buttonLayout=(FlowLayout)buttons.getLayout();
        buttonLayout.setVgap(4);
        buttons.setMaximumSize(new Dimension(Integer.MAX_VALUE,44));
        buttons.add(MistWorkspaceTheme.label("답변 방식 :",12,MistWorkspaceTheme.MUTED,Font.PLAIN));
        tutorMode.setModel(new DefaultComboBoxModel<>(new String[]{"간단한 설명","상세한 설명"}));
        tutorMode.setPreferredSize(new Dimension(96,24));buttons.add(tutorMode);
        tutorMode.setToolTipText("두 모드 모두 쉬운 핵심 설명에서 출발해요. 간단한 설명은 핵심과 필요한 예시에 집중하고, 상세한 설명은 같은 예시의 과정과 조건을 더 풀어줘요.");
        tutorReasoning.setPreferredSize(new Dimension(96,24));buttons.add(tutorReasoning);
        tutorReasoning.getAccessibleContext().setAccessibleName("AI멘토 추론 수준");
        tutorReasoning.setToolTipText("높은 추론은 더 깊게 검토하고, 중간 추론은 빠르게 핵심을 정리해요. 설명 길이와 별도로 선택할 수 있어요.");
        tutorSearchHint.setToolTipText("AI가 필요한 경우에만 웹 검색을 최대 1회 사용합니다. 검색 호출료와 토큰 비용이 추가됩니다.");
        JPanel options=new JPanel();options.setOpaque(false);
        options.setLayout(new BoxLayout(options,BoxLayout.Y_AXIS));
        buttons.setAlignmentX(Component.LEFT_ALIGNMENT);options.add(buttons);
        tutorDocumentConnection.setToolTipText(tutorSearchHint.getText());
        composer.add(options, BorderLayout.NORTH);
        GrowingTutorInput.focusOnBlankSpace(composer,question);
        chat.add(composer, BorderLayout.SOUTH); tutorPanel=chat;
        rightContent.add(chat,"AI멘토"); right.add(rightContent, BorderLayout.CENTER);
        studyColumns.register("AI멘토",null,chat); // Standalone workspace fallback; application moves it to the floating host.
        JPanel visualPage=new JPanel(new BorderLayout()); visualPage.setBackground(Color.WHITE);
        JPanel visualActions=row();JButton backToTutor=new JButton("‹ AI멘토로 돌아가기");
        backToTutor.addActionListener(e->showTutor());
        visualActions.add(backToTutor);visualActions.add(applyVisual);
        applyVisual.addActionListener(e->{showTab("요약");startGeneration(0,true);});
        visualPage.add(visualActions,BorderLayout.NORTH);
        visualPage.add(new SmoothScrollPane(visualDetail),BorderLayout.CENTER);
        rightContent.add(visualPage,"그림 설명");
        studyColumns.register("그림 설명",null,visualPage);
        ask.addActionListener(e -> {if(tutorBusy)cancelTutorReply();else askTutor();});
        InputMap tutorKeys=question.getInputMap(JComponent.WHEN_FOCUSED);
        tutorKeys.put(KeyStroke.getKeyStroke(KeyEvent.VK_ENTER,0),"synesisSendTutor");
        tutorKeys.put(KeyStroke.getKeyStroke(KeyEvent.VK_ENTER,InputEvent.SHIFT_DOWN_MASK),"synesisNewlineTutor");
        question.getActionMap().put("synesisSendTutor",new AbstractAction() {
            @Override public void actionPerformed(java.awt.event.ActionEvent event) { askTutor(); }
        });
        question.getActionMap().put("synesisNewlineTutor",new AbstractAction() {
            @Override public void actionPerformed(java.awt.event.ActionEvent event) { question.replaceSelection("\n"); }
        });
        newChat.addActionListener(e -> confirmNewTutorChat());
        newChat.setToolTipText("이전 대화를 비우고 현재 PDF에서 새로 질문합니다");
        for(JEditorPane pane:new JEditorPane[]{summary,visualDetail}) pane.addHyperlinkListener(e -> {
            if(e.getEventType()==javax.swing.event.HyperlinkEvent.EventType.ACTIVATED) navigate(e.getDescription());
        });
        return right;
    }

    private static JPanel row() { JPanel p = new JPanel(new FlowLayout(FlowLayout.LEFT, 7, 6)); p.setBackground(Color.WHITE); return p; }

    private JButton fontSizeEntry(JSlider slider,String section) {
        JButton entry=new JButton("글자 크기");
        entry.setContentAreaFilled(false);entry.setBorderPainted(false);entry.setFocusPainted(false);
        entry.setMargin(new Insets(0,0,0,0));entry.setForeground(BLUE);
        entry.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        entry.setToolTipText("클릭해서 "+section+" 글자 크기 직접 입력");
        entry.addActionListener(event->promptFontSize(slider,section));
        return entry;
    }

    private void promptFontSize(JSlider slider,String section) {
        while(true) {
            Object answer=JOptionPane.showInputDialog(this,
                section+" 글자 크기를 입력해 주세요 ("+slider.getMinimum()+"~"+slider.getMaximum()+"pt).",
                "글자 크기 직접 입력",JOptionPane.PLAIN_MESSAGE,null,null,
                String.valueOf(slider.getValue()));
            if(answer==null)return;
            try {
                slider.setValue(parseFontSizeInput(answer.toString(),slider.getMinimum(),slider.getMaximum()));
                return;
            } catch(IllegalArgumentException error) {
                JOptionPane.showMessageDialog(this,error.getMessage(),"글자 크기 확인",JOptionPane.WARNING_MESSAGE);
            }
        }
    }

    static int parseFontSizeInput(String input,int minimum,int maximum) {
        String value=input.trim();
        String range="글자 크기는 "+minimum+"~"+maximum+"pt 범위예요. 이 범위 안의 숫자로 입력해 주세요.";
        if(!value.matches("-?\\d+"))
            throw new IllegalArgumentException("글자 크기를 정수로 입력해 주세요. 설정 가능한 범위는 "+minimum+"~"+maximum+"pt예요.");
        int size;
        try {size=Integer.parseInt(value);} catch(NumberFormatException error) {throw new IllegalArgumentException(range);}
        if(size<minimum || size>maximum)throw new IllegalArgumentException(range);
        return size;
    }
    private void styleControls(Component component) {
        if(!(component instanceof JEditorPane) && !(component instanceof JLabel) &&
            !(component instanceof JComponent widget && Boolean.TRUE.equals(widget.getClientProperty("synesis.preserveFont"))))
            component.setFont(new Font(UiFonts.FAMILY,Font.PLAIN,13));
        if(component instanceof JButton button) {
            if(!Boolean.TRUE.equals(button.getClientProperty("synesis.preserveButton")))
                StudyTheme.button(button,button==ask||button==generate);
        } else if(component instanceof JScrollPane scroll) scroll.setBorder(BorderFactory.createEmptyBorder());
        if(component instanceof Container container) for(Component child:container.getComponents()) styleControls(child);
    }
    private static final class TabButton extends dev.synesis.poc.ui.StudyTabStrip.Tab {
        private boolean addMarker;
        TabButton(String title){
            super(title);setPreferredSize(new Dimension(100,40));
            putClientProperty("synesis.preserveButton",true);setToolTipText(title+" · 학습창 열기");
        }
        void setAddMarker(boolean value){
            if(addMarker==value)return;
            addMarker=value;setToolTipText(getText()+(value?" · 새 학습창에 열기":" · 학습창 선택"));repaint();
        }
        @Override protected void paintComponent(Graphics graphics){
            super.paintComponent(graphics);if(!addMarker)return;
            Graphics2D g=(Graphics2D)graphics.create();
            try{
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(getForeground());g.setStroke(new BasicStroke(1.3f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                int x=Math.min(getWidth()-7,(getWidth()+getFontMetrics(getFont()).stringWidth(getText()))/2+4),y=6;
                g.drawLine(x-3,y,x+3,y);g.drawLine(x,y-3,x,y+3);
            }finally{g.dispose();}
        }
    }
    private void updateNavigationAddMarkers(){
        boolean available=studyColumns.count()<2;
        tabButtons.forEach((name,button)->{
            if(button instanceof TabButton tab)tab.setAddMarker(available&&!name.equals("AI멘토")&&!studyColumns.containsView(name));
        });
    }
    private static final class TutorMessageColumn extends JPanel implements Scrollable {
        @Override public Insets getInsets(){return getInsets(new Insets(0,0,0,0));}
        @Override public Insets getInsets(Insets insets){
            super.getInsets(insets);
            int width=getParent() instanceof JViewport viewport?viewport.getWidth():getWidth();
            int extra=Math.max(0,width-SummaryFlow.MAX_READING_WIDTH);
            insets.left+=extra/2;insets.right+=extra-extra/2;
            return insets;
        }
        @Override public Dimension getPreferredScrollableViewportSize(){return getPreferredSize();}
        @Override public int getScrollableUnitIncrement(Rectangle visible,int orientation,int direction){return 12;}
        @Override public int getScrollableBlockIncrement(Rectangle visible,int orientation,int direction){return Math.max(40,visible.height-40);}
        @Override public boolean getScrollableTracksViewportWidth(){return true;}
        @Override public boolean getScrollableTracksViewportHeight(){return false;}
    }
    /** Attachment thumbnails must not trap vertical chat scrolling in their horizontal strip. */
    private static final class TutorPreviewScrollPane extends SmoothScrollPane {
        TutorPreviewScrollPane(Component view) {
            super(view,JScrollPane.VERTICAL_SCROLLBAR_NEVER,JScrollPane.HORIZONTAL_SCROLLBAR_AS_NEEDED);
        }
        @Override protected void processMouseWheelEvent(MouseWheelEvent event) {
            JScrollBar horizontal=getHorizontalScrollBar();
            if(event.isShiftDown() && horizontal.isVisible()
                    && horizontal.getMaximum()>horizontal.getVisibleAmount()) {
                super.processMouseWheelEvent(event);return;
            }
            JScrollPane outer=(JScrollPane)SwingUtilities.getAncestorOfClass(JScrollPane.class,this);
            if(outer==null) {super.processMouseWheelEvent(event);return;}
            Point point=SwingUtilities.convertPoint(this,event.getPoint(),outer);
            outer.dispatchEvent(new MouseWheelEvent(outer,event.getID(),event.getWhen(),event.getModifiersEx(),
                point.x,point.y,event.getXOnScreen(),event.getYOnScreen(),event.getClickCount(),
                event.isPopupTrigger(),event.getScrollType(),event.getScrollAmount(),
                event.getWheelRotation(),event.getPreciseWheelRotation()));
            event.consume();
        }
    }
    private static final class TutorThinkingLabel extends JLabel {
        private boolean transformScale;
        private float visualSize=NORMAL_SIZE;
        private Dimension scaledPreferredSize;
        private static final float NORMAL_SIZE=13f;
        private static final float WAITING_SIZE=NORMAL_SIZE*1.3f;
        TutorThinkingLabel() {
            super(TutorActivity.Stage.PDF.text);
            setFont(new Font(UiFonts.FAMILY,Font.PLAIN,13));
            setOpaque(false);
        }
        @Override public Dimension getPreferredSize(){
            if(!transformScale)return super.getPreferredSize();
            if(scaledPreferredSize==null){
                FontMetrics metrics=getFontMetrics(getFont().deriveFont(WAITING_SIZE));
                scaledPreferredSize=new Dimension(metrics.stringWidth(getText())+2,metrics.getHeight());
            }
            return new Dimension(scaledPreferredSize);
        }
        @Override protected void paintComponent(Graphics graphics) {
            Graphics2D g=(Graphics2D)graphics.create();
            try {
                g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
                if(transformScale){
                    double scale=visualSize/NORMAL_SIZE;
                    g.translate(0,(getHeight()-getFontMetrics(getFont()).getHeight()*scale)/2);
                    g.scale(scale,scale);
                }
                g.setFont(getFont());
                FontMetrics metrics=g.getFontMetrics();
                float width=Math.max(1,metrics.stringWidth(getText()));
                float phase=(System.nanoTime()%2_400_000_000L)/2_400_000_000f;
                float x=phase*width*2-width;
                g.setPaint(new LinearGradientPaint(x,0,x+width,0,
                    new float[]{0,.5f,1},
                    new Color[]{MistWorkspaceTheme.MUTED,new Color(0xd4e2f4),MistWorkspaceTheme.MUTED},
                    MultipleGradientPaint.CycleMethod.REPEAT));
                g.drawString(getText(),0,(transformScale?0:(getHeight()-metrics.getHeight())/2)+metrics.getAscent());
            } finally {g.dispose();}
        }
    }
    static RoundedTutorBubble assistantAnswerBubble(String content,int width,int fontSize,Consumer<String> navigate) {
        return new RoundedTutorBubble(content,false,width,fontSize,navigate,List.of(),true);
    }
    static final class RoundedTutorBubble extends JPanel {
        private final Color fill;
        private final boolean user;
        private final boolean assistantDark;
        private final int padding;
        private JEditorPane text;
        private final List<JComponent> bodyParts=new ArrayList<>();
        private final List<JEditorPane> prosePanes=new ArrayList<>();
        private final Map<String,MathScrollPane> mathPanes=new HashMap<>();
        private final Map<String,SummaryFormulaGroup> readingGroups=new HashMap<>();
        private final Consumer<String> navigate;
        private JScrollPane previewStrip;
        private String displayedContent;
        private int displayedFont, targetWidth, targetHeight;
        private int previewHeight;
        private final TutorThinkingLabel thinkingLabel=new TutorThinkingLabel();
        private int thinkingHeight;
        private boolean thinkingBeforeAnswer;
        private float thinkingFontSize=TutorThinkingLabel.NORMAL_SIZE;
        private double thinkingX=Double.NaN, thinkingY=Double.NaN;
        private double animatedWidth, animatedHeight;
        private long lastResizeNanos;
        RoundedTutorBubble(String content,boolean user,int width,int fontSize,Consumer<String> navigate,
                           List<TutorPreview> previews) {
            this(content,user,width,fontSize,navigate,previews,false);
        }
        RoundedTutorBubble(String content,boolean user,int width,int fontSize,Consumer<String> navigate,
                           List<TutorPreview> previews,boolean assistantDark) {
            // Keep the document at its natural height while the outer shell animates.
            // BorderLayout would squeeze it to each intermediate animation height,
            // invalidating Swing's HTML/math layout and its cached height measurement.
            super(null);
            this.navigate=navigate;
            this.assistantDark=assistantDark;
            this.user=user;this.padding=user?12:16;
            if(!user)putClientProperty("mist.shadow","answer");
            fill=assistantDark?AssistantChatTheme.SURFACE:user?TUTOR_USER_FILL:TUTOR_ASSISTANT_FILL;
            setOpaque(false);setBorder(new EmptyBorder(padding,padding,padding,padding));
            text=tutorHtml(!user);text.setOpaque(false);text.setBorder(null);
            if(assistantDark)AssistantChatTheme.configure(text);
            prosePanes.add(text);
            displayedContent=content;displayedFont=fontSize;
            text.addHyperlinkListener(event->{
                if(event.getEventType()==javax.swing.event.HyperlinkEvent.EventType.ACTIVATED)
                    navigate.accept(event.getDescription());
            });
            int inside=Math.max(80,width-2*padding);
            int height=rebuildBody(content,inside,fontSize);
            if(!previews.isEmpty()) {
                JPanel strip=new JPanel(new FlowLayout(FlowLayout.LEFT,5,3));strip.setOpaque(false);
                for(int i=0;i<previews.size();i++) {
                    TutorPreview preview=previews.get(i);
                    JLabel thumbnail=new JLabel(preview.icon()==null?"PDF":null,preview.icon(),SwingConstants.CENTER);
                    thumbnail.setPreferredSize(new Dimension(68,68));
                    thumbnail.setBorder(BorderFactory.createLineBorder(MistWorkspaceTheme.LINE));
                    thumbnail.setToolTipText((i+1)+". "+preview.name());
                    strip.add(thumbnail);
                }
                JScrollPane scroll=new TutorPreviewScrollPane(strip);
                scroll.setBorder(null);scroll.setOpaque(false);scroll.getViewport().setOpaque(false);
                styleTutorScrollBars(scroll);
                scroll.setBackground(fill);scroll.getViewport().setBackground(fill);
                scroll.setPreferredSize(new Dimension(inside,84));
                previewStrip=scroll;add(scroll);previewHeight=84;
            }
            targetWidth=width;targetHeight=height+previewHeight+2*padding;
            thinkingLabel.setVisible(false);add(thinkingLabel);
            animatedWidth=width;animatedHeight=targetHeight;
            setPreferredSize(new Dimension(width,targetHeight));
        }
        void updateContent(String content,int width,int fontSize) {
            if(content.equals(displayedContent) && width==targetWidth && fontSize==displayedFont)return;
            if(content.equals(displayedContent) && fontSize==displayedFont) {
                reflowWidth(width);
                return;
            }
            displayedContent=content;displayedFont=fontSize;targetWidth=width;
            int inside=Math.max(80,width-2*padding);
            int height=rebuildBody(content,inside,fontSize);
            targetHeight=height+previewHeight+thinkingHeight+2*padding;
            if(lastResizeNanos==0)lastResizeNanos=System.nanoTime();
        }
        void reflowWidth(int width) {
            if(width!=targetWidth) {
                targetWidth=width;
                targetHeight=measureBody(Math.max(80,width-2*padding),displayedFont)+previewHeight+thinkingHeight+2*padding;
            }
            // The divider already supplies the motion. A second size animation
            // would repeatedly lay out text at widths behind the actual pointer.
            animatedWidth=targetWidth;animatedHeight=targetHeight;lastResizeNanos=0;
            setPreferredSize(new Dimension(targetWidth,targetHeight));
            revalidate();
        }
        void prepareAssistantThinking(){
            thinkingLabel.transformScale=true;
            thinkingLabel.visualSize=TutorThinkingLabel.WAITING_SIZE;
            thinkingLabel.setText("생각중이에요…");
            setThinking(true,true);
            targetHeight=Math.max(116,targetHeight);animatedHeight=targetHeight;
            setPreferredSize(new Dimension(targetWidth,targetHeight));
        }
        void repaintAssistantThinking(){
            if(thinkingLabel.isVisible())thinkingLabel.repaint();
        }
        void setThinking(boolean thinking,boolean beforeAnswer) {
            if(thinkingBeforeAnswer!=beforeAnswer) {
                thinkingBeforeAnswer=beforeAnswer;
                if(lastResizeNanos==0)lastResizeNanos=System.nanoTime();
                revalidate();repaint();
            }
            float fontSize=beforeAnswer?TutorThinkingLabel.WAITING_SIZE:TutorThinkingLabel.NORMAL_SIZE;
            if(thinking && !thinkingLabel.isVisible()) {
                thinkingFontSize=fontSize;
                if(assistantDark)thinkingLabel.visualSize=fontSize;
                else thinkingLabel.setFont(thinkingLabel.getFont().deriveFont(fontSize));
            }
            int height=thinking?thinkingLabel.getFontMetrics(thinkingLabel.getFont().deriveFont(assistantDark?TutorThinkingLabel.WAITING_SIZE:fontSize)).getHeight()+8:0;
            if(height==thinkingHeight)return;
            targetHeight+=height-thinkingHeight;thinkingHeight=height;
            thinkingLabel.setVisible(thinking);
            if(!thinking){thinkingX=Double.NaN;thinkingY=Double.NaN;}
            if(lastResizeNanos==0)lastResizeNanos=System.nanoTime();
        }
        private int rebuildBody(String content,int width,int fontSize) {
            for(JComponent part:bodyParts)remove(part);
            bodyParts.clear();
            Set<String> usedMath=new HashSet<>(),usedGroups=new HashSet<>();
            SummarySkin.FormulaPresentation presentation=user?null:SummarySkin.prepare(content);
            if(presentation!=null)content=presentation.body();
            Map<String,Integer> occurrences=new HashMap<>();
            Matcher markers=SLIDE_LENS_MARKER.matcher(content);
            int start=0,prose=0;
            while(markers.find()) {
                if(markers.group(2)==null&&markers.group(4)==null)continue;
                prose=addProse(content.substring(start,markers.start()),prose,fontSize,usedGroups);
                if(markers.group(4)!=null&&presentation!=null) {
                    SummarySkin.FormulaGroup group=presentation.groups().get(markers.group(4));
                    String occurrence="formula/"+group;
                    String key=fontSize+"/"+occurrences.merge(occurrence,1,Integer::sum)+"/"+occurrence;
                    bodyParts.add(readingGroup(key,group,fontSize,usedGroups));
                    start=markers.end();continue;
                }
                String id=markers.group(2);
                StudyMarkdown.ScrollableMath equation=StudyMarkdown.scrollableMath(id);
                if(equation!=null) {
                    String key=fontSize+":"+id+":"+occurrences.merge(id,1,Integer::sum);
                    MathScrollPane scroll=mathPanes.computeIfAbsent(key,ignored->new MathScrollPane(equation,fontSize,true));
                    if(assistantDark) {
                        JEditorPane pane=(JEditorPane)scroll.getViewport().getView();
                        AssistantChatTheme.configure(pane);pane.setText(AssistantChatTheme.document(tutorDocumentHtml(equation.html(),fontSize)));
                        scroll.getViewport().setBackground(fill);scroll.setBackground(fill);
                    }
                    bodyParts.add(scroll);usedMath.add(key);
                }
                start=markers.end();
            }
            addProse(content.substring(start),prose,fontSize,usedGroups);
            readingGroups.keySet().retainAll(usedGroups);
            mathPanes.keySet().retainAll(usedMath);
            for(JComponent part:bodyParts)add(part);
            if(!bodyParts.isEmpty()) {
                JComponent first=bodyParts.getFirst();
                if(first instanceof JEditorPane pane)text=pane;
                else if(first instanceof SummaryFormulaGroup group)text=group.textPane();
                else if(first instanceof JScrollPane scroll&&scroll.getViewport().getView() instanceof JEditorPane pane)text=pane;
            }
            if(text.getParent()==this)setComponentZOrder(text,0);
            return measureBody(width,fontSize);
        }
        private int measureBody(int width,int fontSize) {
            int height=0;
            for(JComponent part:bodyParts) {
                if(part instanceof SummaryFormulaGroup)part.setSize(width,Math.max(1,part.getHeight()));
                int partHeight=part instanceof JEditorPane pane?measureText(pane,width,fontSize):part.getPreferredSize().height;
                part.setPreferredSize(new Dimension(width,partHeight));
                // Scroll view width belongs to the viewport; keep the equation's natural width.
                height+=partHeight;
            }
            return height;
        }
        private SummaryFormulaGroup readingGroup(String key,SummarySkin.FormulaGroup group,int fontSize,Set<String> used) {
            used.add(key);
            return readingGroups.computeIfAbsent(key,ignored->new SummaryFormulaGroup(group,fontSize,navigate,
                assistantDark?AssistantChatTheme.document(tutorDocumentHtml(group.body(),fontSize)):tutorDocumentHtml(group.body(),fontSize),
                PdfWorkspace::styleTutorScrollBars,assistantDark));
        }
        private int addProse(String fragment,int index,int fontSize,Set<String> usedGroups) {
            if(fragment.isBlank())return index;
            if(!user&&(fragment.contains("<table ")||fragment.contains("<pre>"))) {
                String key="prose/"+index+"/"+fontSize+"/"+fragment;
                bodyParts.add(readingGroup(key,new SummarySkin.FormulaGroup(fragment,false),fontSize,usedGroups));
                return index+1;
            }
            // Native viewports also occupy positions; fill any skipped prose cache slots.
            while(index>=prosePanes.size()) {
                JEditorPane pane=tutorHtml(!user);pane.setOpaque(false);pane.setBorder(null);
                pane.addHyperlinkListener(event->{
                    if(event.getEventType()==javax.swing.event.HyperlinkEvent.EventType.ACTIVATED)
                        navigate.accept(event.getDescription());
                });
                prosePanes.add(pane);
            }
            JEditorPane pane=prosePanes.get(index++);
            String html=user?tutorUserDocumentHtml(fragment,fontSize):tutorDocumentHtml(fragment,fontSize);
            if(assistantDark){AssistantChatTheme.configure(pane);html=AssistantChatTheme.document(html);}
            if(user)html=html.replace("p{margin-top:0;margin-bottom:12px;}","p{margin-top:0;margin-bottom:0;}")
                .replace("#45474c","#141414");
            if(!html.equals(pane.getClientProperty("synesis.tutorHtml"))) {
                pane.setText(html);
                pane.putClientProperty("synesis.tutorHtml",html);
            }
            bodyParts.add(pane);
            return index;
        }
        private int measureText(JEditorPane pane,int width,int fontSize) {
            pane.setPreferredSize(null);
            pane.setSize(width,Short.MAX_VALUE);
            javax.swing.text.View root=pane.getUI().getRootView(pane);
            Insets insets=pane.getInsets();
            // modelToView2D forces the same width-dependent layout used by paint,
            // including MathView and paragraph/table margins. A preferred-size
            // query alone can still return the previous document's cached span.
            double lastBottom=0;
            try {
                java.awt.geom.Rectangle2D end=pane.modelToView2D(pane.getDocument().getLength());
                if(end!=null)lastBottom=end.getMaxY();
            } catch(javax.swing.text.BadLocationException ignored) { /* Span still covers the document. */ }
            return Math.max(user?fontSize:fontSize*2,(int)Math.ceil(Math.max(lastBottom,
                root.getPreferredSpan(javax.swing.text.View.Y_AXIS)+insets.top+insets.bottom))+4);
        }
        @Override public void doLayout() {
            // Animated width must not rewrap the text into an unmeasured taller column.
            int inside=Math.max(80,targetWidth-2*padding);
            int y=padding;
            for(JComponent part:bodyParts) {
                int height=part.getPreferredSize().height;
                part.setBounds(padding,y,inside,height);part.doLayout();y+=height;
            }
            Dimension label=thinkingLabel.getPreferredSize();
            Point destination=thinkingDestination(getWidth(),getHeight());
            if(Double.isNaN(thinkingX)){thinkingX=destination.x;thinkingY=destination.y;}
            thinkingLabel.setBounds((int)Math.round(thinkingX),(int)Math.round(thinkingY),
                Math.min(inside,label.width),label.height);
            if(previewHeight>0)previewStrip.setBounds(padding,targetHeight-previewHeight-padding,inside,previewHeight);
        }
        private Point thinkingDestination(int width,int height) {
            Dimension label=thinkingLabel.getPreferredSize();
            return thinkingBeforeAnswer
                ?new Point(padding,Math.max(padding,(height-label.height)/2))
                :new Point(padding,Math.max(padding,Math.min(targetHeight-previewHeight-thinkingHeight-padding,
                    height-previewHeight-label.height-padding)));
        }
        boolean animatingSize(){return lastResizeNanos!=0;}

        boolean animateSize(long now) {
            if(lastResizeNanos==0)return false;
            Dimension previousSize=getPreferredSize();
            Rectangle previousLabel=thinkingLabel.getBounds();
            double elapsed=Math.min(.05,(now-lastResizeNanos)/1_000_000_000.0);
            lastResizeNanos=now;
            // Retarget continuously without restarting the motion for each token.
            double blend=1-Math.exp(-elapsed/.055);
            animatedWidth+=(targetWidth-animatedWidth)*blend;
            animatedHeight+=(targetHeight-animatedHeight)*blend;
            boolean moving=Math.abs(targetWidth-animatedWidth)>.5 || Math.abs(targetHeight-animatedHeight)>.5;
            if(thinkingLabel.isVisible()) {
                float targetFont=thinkingBeforeAnswer?TutorThinkingLabel.WAITING_SIZE:TutorThinkingLabel.NORMAL_SIZE;
                thinkingFontSize+=(targetFont-thinkingFontSize)*(float)(1-Math.exp(-elapsed/.08));
                boolean scaling=Math.abs(targetFont-thinkingFontSize)>.02f;
                if(!scaling)thinkingFontSize=targetFont;
                if(assistantDark)thinkingLabel.visualSize=thinkingFontSize;
                else thinkingLabel.setFont(thinkingLabel.getFont().deriveFont(thinkingFontSize));
                moving|=scaling;
            }
            if(thinkingLabel.isVisible() && !Double.isNaN(thinkingX)) {
                Point destination=thinkingDestination((int)Math.round(animatedWidth),(int)Math.round(animatedHeight));
                double glide=1-Math.exp(-elapsed/.08);
                thinkingX+=(destination.x-thinkingX)*glide;
                thinkingY+=(destination.y-thinkingY)*glide;
                boolean gliding=Math.abs(destination.x-thinkingX)>.5 || Math.abs(destination.y-thinkingY)>.5;
                if(!gliding){thinkingX=destination.x;thinkingY=destination.y;}
                moving|=gliding;
            }
            if(!moving){animatedWidth=targetWidth;animatedHeight=targetHeight;lastResizeNanos=0;}
            Dimension nextSize=new Dimension((int)Math.round(animatedWidth),(int)Math.round(animatedHeight));
            boolean resized=!nextSize.equals(previousSize);
            if(assistantDark&&!resized){
                Dimension label=thinkingLabel.getPreferredSize();
                thinkingLabel.setBounds((int)Math.round(thinkingX),(int)Math.round(thinkingY),label.width,label.height);
                Rectangle damage=previousLabel.union(thinkingLabel.getBounds());damage.grow(1,1);repaint(damage);
                return false;
            }
            setPreferredSize(nextSize);
            doLayout();repaint();
            return moving;
        }
        @Override protected void paintComponent(Graphics graphics) {
            Graphics2D g=(Graphics2D)graphics.create();
            try {
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(fill);g.fillRoundRect(0,0,getWidth(),getHeight(),24,24);
                if(!user){g.setColor(assistantDark?AssistantChatTheme.LINE:MistWorkspaceTheme.INNER_LINE);g.drawRoundRect(0,0,getWidth()-1,getHeight()-1,24,24);}
            } finally {g.dispose();}
            super.paintComponent(graphics);
        }
    }
    private static final class VerticalList extends JPanel implements Scrollable {
        private final ConceptTreeGuides treeGuides=new ConceptTreeGuides();
        @Override public void doLayout(){super.doLayout();treeGuides.layout(this);}
        @Override protected void paintChildren(Graphics graphics){
            super.paintChildren(graphics);
            Graphics copy=graphics.create();try{treeGuides.paint(copy);}finally{copy.dispose();}
        }
        private static final int MAX_READING_WIDTH = (int)Math.round(SummaryFlow.MAX_READING_WIDTH * 1.2);
        @Override public Insets getInsets() {return getInsets(new Insets(0,0,0,0));}
        @Override public Insets getInsets(Insets insets) {
            super.getInsets(insets);
            int margin=Math.max(0,(getWidth()-MAX_READING_WIDTH)/2);
            insets.left+=margin;insets.right+=margin;
            return insets;
        }
        @Override public Dimension getPreferredScrollableViewportSize(){return new Dimension(500,500);}
        @Override public int getScrollableUnitIncrement(Rectangle visible,int orientation,int direction){return 24;}
        @Override public int getScrollableBlockIncrement(Rectangle visible,int orientation,int direction){return Math.max(24,visible.height-40);}
        @Override public boolean getScrollableTracksViewportWidth(){return true;}
        @Override public boolean getScrollableTracksViewportHeight(){return false;}
    }
    private static JEditorPane html() {
        return html(false);
    }
    private static JEditorPane html(boolean wordWrap) {
        JEditorPane p = new StudyHtmlPane(wordWrap); p.setEditable(false); p.setBackground(Color.WHITE);
        p.putClientProperty(JEditorPane.HONOR_DISPLAY_PROPERTIES, true); p.setFont(new Font(UiFonts.FAMILY, Font.PLAIN, 14)); return p;
    }
    private static JEditorPane tutorHtml(boolean reading) {
        JEditorPane pane=html(true);
        if(reading)((StudyHtmlPane)pane).setReadingSkin(true);else useTutorFont(pane);
        return pane;
    }
    private static void useTutorFont(JEditorPane pane){
        // A document-local font resolver uses the bundled Figma font without registering it
        // globally or changing the summary/concept renderer's font metrics.
        var kit=(javax.swing.text.html.HTMLEditorKit)pane.getEditorKit();
        var styles=new javax.swing.text.html.StyleSheet(){
            @Override public Font getFont(javax.swing.text.AttributeSet attributes){
                Font css=super.getFont(attributes);
                Font font=MistWorkspaceTheme.font(css.getStyle(),css.getSize());
                return css.isItalic()?font.deriveFont(css.getStyle(),(float)css.getSize()):font;
            }
        };
        styles.addStyleSheet(kit.getStyleSheet());
        pane.setDocument(new javax.swing.text.html.HTMLDocument(styles));
    }
    private static void styleTutorScrollBars(JScrollPane scroll) {
        scroll.putClientProperty("synesis.tutorScroll",true);
        scroll.getVerticalScrollBar().setUI(new dev.synesis.poc.ui.FadingScrollBarUI(MistWorkspaceTheme.MUTED,.38f));
        scroll.getHorizontalScrollBar().setUI(new dev.synesis.poc.ui.FadingScrollBarUI(MistWorkspaceTheme.MUTED,.38f));
    }
    private void choosePdf() {
        JFileChooser chooser = new JFileChooser(); chooser.setFileFilter(new FileNameExtensionFilter("PDF 문서", "pdf"));
        chooser.setMultiSelectionEnabled(true);
        if(chooser.showOpenDialog(this)==JFileChooser.APPROVE_OPTION) {
            List<Path> chosen=Arrays.stream(chooser.getSelectedFiles()).map(File::toPath).toList();
            if(chosen.isEmpty() && chooser.getSelectedFile()!=null)
                chosen=List.of(chooser.getSelectedFile().toPath());
            if(!chosen.isEmpty())importPdfs(chosen);
        }
    }

    public void setPdfImportHandler(java.util.function.Consumer<List<Path>> handler) {
        pdfImportHandler=handler;
    }

    private void importPdfs(List<Path> paths) {
        if(pdfImportHandler!=null)pdfImportHandler.accept(paths);
        else if(!paths.isEmpty())openPdf(paths.get(0));
    }

    /** Selecting an engine does not send source material or start a worker. */
    private boolean chooseGenerationEngine() {
        if(GraphicsEnvironment.isHeadless()) {generationEngineSelected=true;return true;}
        JComboBox<String> engines = new JComboBox<>(PdfStudyStrategy.ENGINE_LABELS);
        engines.setSelectedIndex(Arrays.asList(PdfStudyStrategy.ENGINE_IDS).indexOf(PdfStudyStrategy.DEFAULT));
        Object[] message = {"이 PDF의 강의해설·개념 정리를 생성할 엔진을 선택해 주세요.", engines,
            "저장된 결과가 있으면 먼저 불러와요."};
        String[] options = {"선택", "취소"};
        int action = JOptionPane.showOptionDialog(this, message, "생성 엔진 선택",
            JOptionPane.DEFAULT_OPTION, JOptionPane.QUESTION_MESSAGE, null, options, options[0]);
        if(action != 0)return false;
        selectGenerationEngine(PdfStudyStrategy.ENGINE_IDS[engines.getSelectedIndex()]);
        return true;
    }

    public void selectGenerationEngine(String strategy) {
        int selected=Arrays.asList(STRATEGY_IDS).indexOf(strategy);
        if(selected<0)throw new IllegalArgumentException("Unknown study engine: "+strategy);
        if(summaryStrategy.getSelectedIndex()!=selected)summaryStrategy.setSelectedIndex(selected);
        generationEngineSelected=true;
    }

    /** Explicit library reopen only; an ongoing generation is never replaced. */
    public void chooseEngineForOpenedPdf() {
        if(closed || busy || externalBatchActive || index==null)return;
        if(chooseGenerationEngine())startGeneration(0,false);
    }

    public void openPdf(Path path) {
        openPdf(path, null);
    }

    public void openPdf(Path path, String displayName) {
        if(closed) return;
        if(autoGenerateOnImport && !chooseGenerationEngine())return;
        if(automaticStudy) {
            automaticStudyError=null;
            selectGenerationEngine(PdfStudyStrategy.DEFAULT);
            scope.setSelectedIndex(0);
        }
        saveTutorConversation();
        externalBatchActive=false;observedBatchOrder=-1;
        initialPdfEntrance=true;
        quizWorkbookOpenRevision++;
        quizGenerating=false;
        pendingGenerationReport=null;
        setGenerationProgress(null);
        long started=System.nanoTime();
        int epoch = generation.incrementAndGet(); processes.cancel(); releaseStudyAdmission(); renderGeneration.incrementAndGet();
        hierarchyProjectionAttempts.clear();
        tutorGeneration.incrementAndGet();tutorProcesses.cancel();tutorBusy=false;
        setBusy(true, "PDF 여는 중…");
        files.execute(() -> {
            try {
                PdfSource loaded = PdfSource.open(path,pdfStorageRoot,displayName);
                JsonObject savedTutor;
                try{savedTutor=TutorConversationStore.read(loaded.folder);}
                catch(Exception failure){closeSource(loaded);throw failure;}
                SwingUtilities.invokeLater(() -> {
                    if(closed || epoch!=generation.get()) { closeSource(loaded); return; }
                    PdfLocation previousLocation=currentPdfLocation();
                    PdfSource old = source; source=loaded; quiz.reset(loaded.count,loaded.id); index=null; textSelection.reset(); generated=null; comparisonReport=null; products.clear(); clearLiveSummary(); expandedEasySummaries.clear();expandedConcepts.clear();expandedEasyConcepts.clear();expandedSlideLens.clear();pendingSlideLens.clear();loadingSummaryLensAnchors.clear();slideLensWidths.clear();slideLensImages.clear();slideLensErrors.clear();selectedSteps.clear();summaryStepFlows.clear();visualNotices.clear();exitImageSelection();page=1;panelAnchorTimer.stop();panelLayoutAnchor=null;pendingLayoutAnchor=null;hiddenPdfAnchor=null;restoreTutorConversation(savedTutor);
                    conceptCards.clear();conceptSelectionSources.clear();conceptProduct="";conceptOverview.resetDocument();
                    if(autoGenerateOnImport || automaticStudy)
                        setGenerationProgress(new GenerationProgress(loaded.id,loaded.name,0,"PDF 준비 중",false,false));
                    scrollPageTimer.stop();
                    clearViewerImages();pageLayouts.clear();
                    if(!generationEngineSelected)summaryStrategy.setSelectedIndex(Arrays.asList(STRATEGY_IDS).indexOf(PdfStudyStrategy.DEFAULT));
                    closeSource(old);
                    updatePdfNameLabel(loaded.name);
                    pageNumber.setModel(new SpinnerNumberModel(1,1,loaded.count,1)); pageLabel.setText("/ "+loaded.count);
                    firePropertyChange(PDF_LOCATION_PROPERTY,previousLocation,currentPdfLocation());
                    firePropertyChange(PDF_OPENED_PROPERTY,null,currentPdfLocation());
                    searchItems.clear(); renderSummary(); showConcepts();
                    renderTutor(false);
                    showPage(1); resetOpenedDocumentScroll(loaded,epoch);
                    prepare(false,started);
                });
            } catch(Exception error) {
                onEdt(epoch, () -> {
                    String message = "PDF를 열 수 없어요. 암호 보호나 파일 손상을 확인해 주세요.";
                    setBusy(false,message);
                    firePropertyChange(PDF_OPEN_FAILED_PROPERTY,null,message);
                    if(isShowing())showError(message+"\n소요 시간: "+formatElapsed(System.nanoTime()-started));
                });
            }
        });
    }

    public void setCurrentPdfDisplayName(String displayName) {
        if (source == null || displayName == null || displayName.isBlank() || displayName.equals(source.name)) return;
        source.name = displayName;
        updatePdfNameLabel(displayName);
        GenerationProgress progress = generationProgress;
        if (progress != null) setGenerationProgress(new GenerationProgress(progress.documentId(), displayName,
                progress.percent(), progress.stage(), progress.finished(), progress.failed(), progress.needsReview()));
    }

    private void updatePdfNameLabel(String name) {
        filename.setText(name.length() > 28 ? name.substring(0, 25) + "…" : name);
        filename.setToolTipText(name);
    }

    private void prepare(boolean retryFailed) {
        prepare(retryFailed,System.nanoTime());
    }

    private void prepare(boolean retryFailed,long started) {
        PdfSource target = source; if(target==null || closed) return;
        boolean restoreQuiz=index==null;
        int epoch=generation.get(), ticket=processes.ticket();
        setSummaryActivity(SummaryActivityBar.State.RUNNING);
        setBusy(true,"분석 중 · 페이지별 원문 준비");
        jobs.execute(() -> {
            try {
                if(closed || epoch!=generation.get()) return;
                Files.deleteIfExists(target.folder.resolve("cancel"));
                List<String> args=new ArrayList<>(List.of("prepare","--folder",target.folder.toString()));
                if(retryFailed) args.add("--retry");
                processes.run("pdf_pipeline.py",args,ticket,event -> handleProgress(epoch,event));
                JsonObject value=readJson(target.folder.resolve("document.json"));
                if(!target.id.equals(str(value,"documentId"))) throw new IllegalStateException("문서 식별자 불일치");
                JsonObject savedComparison=null;
                try {savedComparison=readJson(target.folder.resolve("comparison/latest-report.json"));}
                catch(Exception ignored) { /* This PDF has no prior comparison yet. */ }
                JsonObject priorComparison=savedComparison;
                // A fresh import has nothing to recover. Starting a second Python
                // process here only delayed grouping and the first visible result.
                JsonObject partial=Files.isDirectory(target.folder.resolve(strategyFolder(summaryStrategyId())))
                    ?recoverPartial(target,ticket,"document",0,str(value,"fingerprint")):null;
                Map<String,JsonObject> savedProducts=loadSavedProducts(target.folder,target.id,value);
                List<QuizWorkbook> priorWorkbooks=restoreQuiz?QuizWorkbookStore.load(target.folder,target.id,value):List.of();
                onEdt(epoch,()->{
                    index=value;
                    comparisonReport=priorComparison!=null && target.id.equals(str(priorComparison,"documentId"))?priorComparison:null;
                    products.clear();products.putAll(savedProducts);hierarchyProjectionAttempts.clear();
                    if(partial!=null) {
                        // Local display upgrades keep saved prose intact on disk.
                        if(partial.has("hierarchy"))products.put(resultProductKey(partial),partial);
                        else products.putIfAbsent(resultProductKey(partial),partial);
                    }
                    // Keep the default (or explicit selection on retry); old results stay selectable.
                    selectProduct();
                    int missing=value.getAsJsonArray("incompletePages").size();
                    if(!autoGenerateOnImport && !automaticStudy && !externalBatchActive)setSummaryActivity(SummaryActivityBar.State.IDLE);
                    setBusy(false,missing==0?"글자 추출 완료 · 강의 해설 생성 대기":"글자 추출 실패 "+missing+"쪽 · 재시도 가능");
                    renderSummary(); if(generated!=null && !autoGenerateOnImport)fadeInSavedSummary(); showConcepts(); updateOriginal(); setControls();
                    if(restoreQuiz)quiz.setWorkbooks(priorWorkbooks);
                    quizGenerating=backgroundQuizzes.running(target.id);
                    if(quizGenerating)quiz.setGenerating(true,"문제를 생성중이에요.");
                    renderTutor(false);
                    resetOpenedDocumentScroll(target,epoch);
                    firePropertyChange(PDF_PREPARED_PROPERTY,null,currentPdfLocation());
                    if(automaticStudy)startAutomaticStudy(System.nanoTime()-started,false);
                    else if(autoGenerateOnImport) {
                        long preparationNanos=System.nanoTime()-started;
                        scope.setSelectedIndex(0);
                        startGeneration(preparationNanos);
                    }
                });
            } catch(Exception error) {
                onEdt(epoch,()->{
                    String message = error.getMessage()==null?"PDF 원문을 준비하지 못했어요.":error.getMessage();
                    finishGeneration(true,"PDF 준비 중단");
                    setBusy(false,"분석 중단 · PDF 열람 가능");
                    firePropertyChange(PDF_PREPARE_FAILED_PROPERTY,null,message);
                    if(automaticStudy)showGenerationError(message);
                    else if(isShowing())showError(message+"\n소요 시간: "+formatElapsed(System.nanoTime()-started));
                });
            }
        });
    }

    private void resetOpenedDocumentScroll(PdfSource target,int epoch) {
        SwingUtilities.invokeLater(() -> {
            if(closed || source!=target || epoch!=generation.get())return;
            summary.setCaretPosition(0);
            summaryScroll.getViewport().setViewPosition(new Point(0,0));
            conceptScroll.getViewport().setViewPosition(new Point(0,0));
            original.setCaretPosition(0);
            if(page==1 && !pageLayouts.isEmpty())scrollToPage(1);
        });
    }

    private void handleProgress(int epoch,JsonObject event) {
        handleProgress(epoch,event,-1);
    }
    private void handleProgress(int epoch,JsonObject event,long batchOrder) {
        if(str(event,"type").equals("summary_overview_delta")) {
            PdfSource target=source;if(target==null || liveGenerationKey==null)return;
            if(!STREAMING_OVERVIEW_STRATEGIES.contains(str(event,"strategy")) || !summaryStrategyId().equals(str(event,"strategy")))return;
            try {
                long sequence=event.get("sequence").getAsLong();
                String key=productKey(str(event,"scope"),event.get("selectionPage").getAsInt());
                JsonObject draft=event.getAsJsonObject("overview").deepCopy();
                boolean discard=event.has("discard")&&event.get("discard").getAsBoolean();
                onEdt(epoch,()->{
                    if(source!=target || !key.equals(liveGenerationKey) || batchOrder>=0&&batchOrder!=liveBatchOrder
                            || liveOverviewComplete || sequence<=liveOverviewSequence)return;
                    liveOverviewSequence=sequence;
                    if(discard) {
                        liveOverview=null;liveOverviewStreamPane=null;renderSummary(true);return;
                    }
                    if(str(draft,"body").isBlank())return;
                    liveOverviewStreaming=true;liveOverview=draft;firstSummaryAppeared();
                    if(liveOverviewStreamPane==null)renderSummary(true);
                    refreshStreamingSummary();startLiveSummaryMotion();
                });
            }catch(RuntimeException ignored){ /* Final validated flow replaces every draft. */ }
            return;
        }
        if(str(event,"type").equals("summary_overview_ready")) {
            PdfSource target=source;if(target==null || liveGenerationKey==null)return;
            try {
                if(!str(event,"strategy").equals(summaryStrategyId()))return;
                Path resultPath=Path.of(str(event,"path")).toAbsolutePath().normalize();
                if(!resultPath.startsWith(target.folder.toAbsolutePath().normalize()))return;
                JsonObject partial=readJson(resultPath);
                JsonObject overview=partial.has("overview") && partial.get("overview").isJsonObject()
                    ?partial.getAsJsonObject("overview"):null;
                if(overview==null || str(overview,"body").isBlank())return;
                String key=productKey(str(event,"scope"),event.get("selectionPage").getAsInt());
                onEdt(epoch,()->{
                    if(source!=target || !key.equals(liveGenerationKey) || batchOrder>=0 && batchOrder!=liveBatchOrder)return;
                    liveOverview=overview.deepCopy();liveOverviewComplete=true;
                    liveOverviewStreaming=STREAMING_OVERVIEW_STRATEGIES.contains(str(event,"strategy"));
                    firstSummaryAppeared();
                    renderSummary(true);startLiveSummaryMotion();
                });
            } catch(Exception ignored) { /* Final saved result remains the recovery path. */ }
            return;
        }
        if(str(event,"type").equals("study_timeline")) {
            onEdt(epoch,()->{
                int percent=event.get("percent").getAsInt();
                String stage=str(event,"stage");
                // The separate generation worker replays preparation stages.
                // Keep both the bar and its description at the completed phase.
                if(generationProgress!=null && !generationProgress.finished()
                        && percent<generationProgress.percent())return;
                String[] message=switch(stage) {
                    case "split_start","split_done" -> new String[]{"SYNESIS.PRO 모델이 PDF를 잘게 쪼개고 있어요.","문단, 제목, 수식, 사진의 의미를 파악하고 있어요."};
                    case "group_start","group_progress","group_done" -> new String[]{"관련 내용을 의미 단위로 묶고 있어요.","이어지는 설명과 근거를 정리하고 있어요."};
                    case "overview_start","overview_done" -> new String[]{"이 강의의 흐름을 정리하고 있어요.","의미 단위의 제목을 연결하고 있어요."};
                    case "units_ready","unit_done" -> new String[]{"강의 해설과 개념을 정리하고 있어요.","완료된 단위가 차례로 반영되고 있어요."};
                    default -> new String[]{"결과를 저장하고 있어요.","조금만 기다려 주세요."};
                };
                if(stage.equals("group_progress") && event.has("completedWindows") && event.has("totalWindows")) {
                    message[1]="묶음 판단 "+event.get("completedWindows").getAsInt()+"/"
                        +event.get("totalWindows").getAsInt()+"구간 완료";
                } else if(stage.equals("unit_done") && event.has("completedUnits") && event.has("totalUnits")) {
                    int done=event.get("completedUnits").getAsInt();
                    message[1]=done>0 && done%7==0?"귀여운 고양이를 잠깐 돌보고 있어요. 곧 이어서 정리할게요."
                        :"생성 단위 "+done+"/"+event.get("totalUnits").getAsInt()+"개 완료";
                }
                status.setText(message[0]+" · "+message[1]);
                status.setToolTipText(message[0]+" · "+message[1]);
                if(generationProgress!=null && !generationProgress.finished())
                    setGenerationProgress(new GenerationProgress(generationProgress.documentId(),
                        generationProgress.documentName(),Math.min(99,percent),message[0],false,false));
            });
            return;
        }
        if(str(event,"type").equals("page_analysis_ready")) {
            PdfSource target=source;if(target==null)return;
            try {JsonObject value=readJson(target.folder.resolve("document.json"));
                onEdt(epoch,()->{if(source==target){index=value;updateOriginal();}});
            }catch(Exception ignored){}
            return;
        }
        if(str(event,"type").equals("summary_unit_delta")) {
            PdfSource target=source;
            if(target==null || liveGenerationKey==null)return;
            try {
                int number=event.get("unit").getAsInt(),total=event.get("total").getAsInt();
                long sequence=event.get("sequence").getAsLong();
                String key=productKey(str(event,"scope"),event.get("selectionPage").getAsInt());
                if(number<1 || number>total || sequence<1 || !str(event,"strategy").equals(summaryStrategyId()))return;
                boolean discard=event.has("discard")&&event.get("discard").getAsBoolean();
                JsonObject draft=!discard&&event.has("summary")&&event.get("summary").isJsonObject()
                    ?event.getAsJsonObject("summary").deepCopy():null;
                if(!discard && (draft==null || str(draft,"body").isBlank()))return;
                onEdt(epoch,()->{
                    if(source!=target || !key.equals(liveGenerationKey) || batchOrder>=0 && batchOrder!=liveBatchOrder || liveSummarySections.containsKey(number)
                        || liveSummaryDiscarded.contains(number)
                        || sequence<=liveSummaryDraftSequences.getOrDefault(number,0L))return;
                    liveSummaryDraftSequences.put(number,sequence);
                    if(discard) {
                        liveSummaryDiscarded.add(number);liveSummaryDrafts.remove(number);
                        liveSummaryDraftPanes.remove(number);liveSummaryDraftStructureDirty=true;
                    } else {
                        if(!liveSummaryDrafts.containsKey(number))liveSummaryDraftStructureDirty=true;
                        liveSummaryDrafts.put(number,draft);
                        firstSummaryAppeared();
                    }
                    liveSummaryTotal=total;
                    refreshStreamingSummary();
                });
            }catch(RuntimeException ignored){ /* A partial display cannot replace the canonical result. */ }
            return;
        }
        if(str(event,"type").equals("summary_unit_ready")) {
            PdfSource target=source;
            if(target==null || liveGenerationKey==null)return;
            try {
                int number=event.get("unit").getAsInt(),total=event.get("total").getAsInt();
                Path path=Path.of(str(event,"path")).toAbsolutePath().normalize();
                Path generatedFolder=target.folder.resolve("generated").toAbsolutePath().normalize();
                if(number<1 || number>total || !str(event,"strategy").equals(summaryStrategyId()) || !path.startsWith(generatedFolder) ||
                        !path.getFileName().toString().equals(String.format(Locale.ROOT,"unit-%05d.json",number-1)))return;
                JsonObject unit=readJson(path);
                if(!unit.has("summary") || !unit.get("summary").isJsonObject())return;
                String key=productKey(str(event,"scope"),event.get("selectionPage").getAsInt());
                onEdt(epoch,()->{
                    if(source!=target || !key.equals(liveGenerationKey) || batchOrder>=0 && batchOrder!=liveBatchOrder)return;
                    boolean wasStreaming=liveSummaryDrafts.remove(number)!=null;
                    liveSummaryDraftPanes.remove(number);
                    liveSummarySections.put(number,unit.getAsJsonObject("summary"));
                    liveConceptUnits.put(number,unit.has("concepts") && unit.get("concepts").isJsonArray()
                        ?unit.getAsJsonArray("concepts").deepCopy():new JsonArray());
                    String content=str(unit.getAsJsonObject("summary"),"body");
                    liveSummaryVisible.put(number,wasStreaming||unit.getAsJsonObject("summary").has("hierarchy")||isEmptyStudyPlaceholder(unit.getAsJsonObject("summary"))
                        ? content.codePointCount(0,content.length()) : 0);
                    if(!wasStreaming&&!unit.getAsJsonObject("summary").has("hierarchy"))liveSummaryFades.put(number,new TutorStreamFade(0xffffff,0x182234));
                    boolean totalKnown=!event.has("totalKnown") || event.get("totalKnown").getAsBoolean();
                    liveSummaryTotal=totalKnown?total:0;
                    status.setText("강의 해설 생성 중 · 구간 "+liveSummarySections.size()+"/"+(totalKnown?Integer.toString(total):"계산 중")+" 완료");
                    if(hasLiveSummaryContent())firstSummaryAppeared();
                    refreshLiveSummaryPreview();
                    startLiveSummaryTimer();
                });
            } catch(Exception ignored) { /* Keep the final result path available if a preview cannot be read. */ }
            return;
        }
        if(str(event,"type").equals("progress")) onEdt(epoch,()->{
            int current=event.get("page").getAsInt(), total=event.get("total").getAsInt();
            String stage=str(event,"stage");
            String strategy=summaryStrategyId();
            if(PdfStudyStrategy.selectable(strategy) && !strategy.equals("newest-m1") && !stage.equals("PDF 글자 직접 추출"))return;
            status.setText("분석 중 · "+stage+" · "+current+"/"+total);
            if(generationProgress!=null && !generationProgress.finished()) {
                int percent=stage.equals("PDF 글자 직접 추출")
                    ?Math.max(generationProgress.percent(),Math.min(2,(int)(2d*current/Math.max(1,total))))
                    :Math.max(generationProgress.percent(),generationPercent(stage,current,total));
                setGenerationProgress(new GenerationProgress(generationProgress.documentId(),
                    generationProgress.documentName(),percent,stage,false,false));
            }
        });
    }

    static int generationPercent(String stage,int current,int total) {
        double fraction=Math.max(0,Math.min(1,current/(double)Math.max(1,total)));
        if(stage.contains("원문 판독") || stage.contains("저장 판독"))return (int)Math.round(35*fraction);
        if(stage.contains("연결과 예시"))return 35+(int)Math.round(15*fraction);
        if(stage.contains("요약과 개념"))return 50+(int)Math.round(42*fraction);
        if(stage.contains("학습 흐름"))return 96;
        if(stage.contains("전체 요약 통합"))return 85+(int)Math.round(10*fraction);
        return Math.min(94,(int)Math.round(80*fraction));
    }

    private void setGenerationProgress(GenerationProgress next) {
        GenerationProgress previous=displayGenerationProgress(generationProgress);
        generationProgress=next;
        if(next==null)firstSummaryShown=false;
        GenerationProgress displayed=displayGenerationProgress(next);
        summaryActivity.setProgress(displayed==null?0:displayed.percent());
        setSummaryActivity(next==null?SummaryActivityBar.State.IDLE:!next.finished()
            ?SummaryActivityBar.State.RUNNING:next.failed()?SummaryActivityBar.State.STOPPED:SummaryActivityBar.State.IDLE);
        firePropertyChange(GENERATION_PROGRESS_PROPERTY,previous,displayed);
    }

    private void finishGeneration(boolean failed,String stage) {
        finishGeneration(failed,false,stage);
    }

    private void finishGeneration(boolean failed,boolean needsReview,String stage) {
        releaseStudyAdmission();
        if(generationProgress==null) {setSummaryActivity(failed?SummaryActivityBar.State.STOPPED:SummaryActivityBar.State.IDLE);return;}
        setGenerationProgress(new GenerationProgress(generationProgress.documentId(),
            generationProgress.documentName(),failed?generationProgress.percent():100,
            stage,true,failed,needsReview));
    }

    static int pendingStudyPageCount(JsonObject result) {
        if(result==null)return 0;
        if(result.has("incompleteStudyPages") && result.get("incompleteStudyPages").isJsonArray())
            return result.getAsJsonArray("incompleteStudyPages").size();
        return result.has("coverageComplete") && result.get("coverageComplete").isJsonPrimitive()
            && result.getAsJsonPrimitive("coverageComplete").isBoolean()
            && !result.get("coverageComplete").getAsBoolean()?1:0;
    }

    private GenerationProgress displayGenerationProgress(GenerationProgress value) {
        if(value==null || value.finished())return value;
        return new GenerationProgress(value.documentId(),value.documentName(),
            StudyLoadingProgress.display(value.percent(),firstSummaryShown),
            (firstSummaryShown?"전체 생성 · ":"첫 요약 준비 · ")+value.stage(),false,value.failed(),value.needsReview());
    }
    private void firstSummaryAppeared() {
        if(firstSummaryShown)return;
        GenerationProgress previous=displayGenerationProgress(generationProgress);
        if(generationProgress!=null && !generationProgress.finished()) {
            GenerationProgress milestone=new GenerationProgress(generationProgress.documentId(),
                generationProgress.documentName(),100,"첫 요약 준비 완료",false,false);
            summaryActivity.setProgress(100);
            firePropertyChange(GENERATION_PROGRESS_PROPERTY,previous,milestone);
        }
        firstSummaryShown=true;
        if(generationProgress!=null)setGenerationProgress(generationProgress);
    }
    public GenerationProgress generationProgress(){return displayGenerationProgress(generationProgress);}
    public boolean generationQueued(){return studyAdmission!=null && studyAdmission.waiting;}

    private void releaseStudyAdmission() {
        StudyAdmission previous=studyAdmission;studyAdmission=null;
        if(previous!=null)previous.release();
    }

    /** Admission spans both planning and generation, including their EDT handoff. */
    void admitStudyGeneration(Runnable ready) {
        PdfSource target=source;int epoch=generation.get();
        StudyAdmission admitted=new StudyAdmission();studyAdmission=admitted;
        setBusy(true,"앞선 PDF 생성 완료 대기 중");
        setGenerationProgress(new GenerationProgress(target.id,target.name,0,"앞선 PDF 생성 완료 대기 중",false,false));
        try {admitted.future=jobs.submit(()->{
            try {
                admitted.permit=studyQueue.acquire();
                if(admitted.cancelled||closed||source!=target||generation.get()!=epoch){admitted.release();return;}
                SwingUtilities.invokeLater(()->{
                    if(admitted.cancelled||closed||source!=target||generation.get()!=epoch||studyAdmission!=admitted){admitted.release();return;}
                    admitted.waiting=false;
                    try {ready.run();}
                    catch(RuntimeException error){finishGeneration(true,"강의 해설 생성 중단");setBusy(false,"강의 해설 생성 중단");showGenerationError(error.getMessage());}
                });
            }catch(InterruptedException interrupted){Thread.currentThread().interrupt();}
        });}catch(RejectedExecutionException closedQueue){admitted.release();studyAdmission=null;}
    }

    void showPage(int value) {
        if(source==null || value<1 || value>source.count) return;
        panelAnchorTimer.stop();panelLayoutAnchor=null;pendingLayoutAnchor=null;
        scrollPageTimer.stop();
        boolean unchanged=page==value;
        setCurrentPage(value);
        if(unchanged) {
            updateOriginal();setControls();
            if(scope.getSelectedIndex()!=0) {selectProduct();renderSummary();showConcepts();}
        }
        if(pageLayouts.size()!=source.count) renderPage();
        else scrollToPage(value);
    }

    private void setCurrentPage(int value) {
        if(page==value) return;
        exitImageSelection();
        PdfLocation previousLocation=currentPdfLocation();
        int previousPage=page;
        page=value;
        repaintPageOutline(previousPage);repaintPageOutline(page);
        if(((Number)pageNumber.getValue()).intValue()!=page) pageNumber.setValue(page);
        firePropertyChange(PDF_LOCATION_PROPERTY,previousLocation,currentPdfLocation());
        updateOriginal();setControls();thumbnailCanvas.repaint();
        if(scope.getSelectedIndex()!=0) {selectProduct();renderSummary();showConcepts();}
    }

    private ZoomAnchor centeredPdfPageAnchor() {
        int displayedPage=((Number)pageNumber.getValue()).intValue();
        return new ZoomAnchor(displayedPage,.5,.5,-1,-1);
    }

    private void preservePdfPageForPanelLayout() {
        if(!pdfVisible || source==null || sourceTabs.getSelectedIndex()!=0)return;
        scrollPageTimer.stop();
        // The displayed page number is captured BEFORE the split changes. Centering uses the
        // destination viewport, never pixel offsets from the previous layout.
        if(panelLayoutAnchor==null)panelLayoutAnchor=centeredPdfPageAnchor();
        pendingLayoutAnchor=panelLayoutAnchor;
        panelAnchorTimer.setRepeats(false);
        if(!outerPanelLayoutChanging)panelAnchorTimer.restart();
    }

    public void preparePanelLayoutChange() {
        outerPanelLayoutChanging=true;
        panelAnchorTimer.stop();
        preservePdfPageForPanelLayout();
    }

    public void completePanelLayoutChange() {
        outerPanelLayoutChanging=false;
        panelAnchorTimer.stop();
        finishPanelPageLayout();
    }

    private void finishPanelPageLayout() {
        if(closed || source==null || panelLayoutAnchor==null || outerPanelLayoutChanging)return;
        if(LayoutMotionPanel.defer(viewer,"pdf-layout",this::finishPanelPageLayout))return;
        ZoomAnchor saved=panelLayoutAnchor;
        renderPage(saved,()->{
            if(panelLayoutAnchor!=saved || outerPanelLayoutChanging || panelAnchorTimer.isRunning())return;
            // Commit the viewport/canvas dimensions before restoring scroll.
            // Otherwise a later viewport layout can clamp to the OLD canvas size.
            restoreZoomAnchor(saved);
            imageScroll.doLayout();imageScroll.getViewport().doLayout();
            if(Math.abs(pdfLayoutWidth()-lastViewportWidth)>8 &&
                    "너비 맞춤".equals(activePdfZoom().getSelectedItem())) {
                SwingUtilities.invokeLater(this::finishPanelPageLayout);return;
            }
            restoreZoomAnchor(saved);
            lastViewportHeight=imageScroll.getViewport().getHeight();
            scrollPageTimer.stop();pendingLayoutAnchor=null;panelLayoutAnchor=null;
        });
    }

    private ZoomAnchor captureZoomAnchor(Point canvasPoint,Point viewportPoint) {
        if(pageLayouts.isEmpty())return null;
        Rectangle visible=imageScroll.getViewport().getViewRect();
        Point point=canvasPoint==null?new Point(visible.x+visible.width/2,visible.y+visible.height/2):canvasPoint;
        Point relative=viewportPoint==null?new Point(visible.width/2,visible.height/2):viewportPoint;
        PageLayout layout=textPageAt(point,false);
        if(layout==null)return null;
        Rectangle bounds=layout.bounds();
        return new ZoomAnchor(layout.number(),
            Math.max(0,Math.min(1,(point.x-bounds.x)/(double)Math.max(1,bounds.width))),
            Math.max(0,Math.min(1,(point.y-bounds.y)/(double)Math.max(1,bounds.height))),
            relative.x,relative.y);
    }

    private void changePdfZoom(int direction,Point canvasPoint,Point viewportPoint) {
        if(source==null || direction==0)return;
        double current=currentPdfZoomPercent();
        int step=pdfOnlyScreen!=null?10:5;
        int next=(int)Math.round(current+(direction>0?step:-step));
        next=Math.max(PDF_ZOOM_STEPS[0],Math.min(PDF_ZOOM_STEPS[PDF_ZOOM_STEPS.length-1],next));
        if(direction>0 && next<=current || direction<0 && next>=current)return;
        selectPdfZoom(next,canvasPoint,viewportPoint);
    }

    private static DefaultComboBoxModel<String> pdfZoomModel() {
        DefaultComboBoxModel<String> model=new DefaultComboBoxModel<>();model.addElement("너비 맞춤");
        for(int percent:PDF_ZOOM_STEPS)model.addElement(percent+"%");
        return model;
    }
    private static JComboBox<String> pdfZoomSelector(String initial) {
        DefaultComboBoxModel<String> model=pdfZoomModel();model.setSelectedItem(initial);
        return new JComboBox<>(model);
    }
    private JComboBox<String> activePdfZoom() {return pdfOnlyScreen==null?zoom:fullZoom;}
    private void pdfZoomChanged(JComboBox<String> control) {
        if(!updatingPdfZoom && control==activePdfZoom())renderPage(captureZoomAnchor(null,null));
    }

    private double currentPdfZoomPercent() {
        String selected=(String)activePdfZoom().getSelectedItem();
        if("너비 맞춤".equals(selected)) {
            Dimension size=source.pageSize(page);
            return 100d*Math.max(240,Math.max(320,imageScroll.getViewport().getWidth())-32)/Math.max(1,size.width);
        }
        return Double.parseDouble(selected.replace("%",""));
    }

    private void changePdfZoomFine(int direction,Point canvasPoint,Point viewportPoint) {
        if(source==null || direction==0)return;
        double current=currentPdfZoomPercent();
        int next=direction>0?(int)Math.floor(current)+1:(int)Math.ceil(current)-1;
        next=Math.max(PDF_ZOOM_STEPS[0],Math.min(PDF_ZOOM_STEPS[PDF_ZOOM_STEPS.length-1],next));
        if(direction>0 && next<=current || direction<0 && next>=current)return;
        selectPdfZoom(next,canvasPoint,viewportPoint);
    }

    private void selectPdfZoom(int percent,Point canvasPoint,Point viewportPoint) {
        String target=percent+"%";
        boolean animate=pdfOnlyScreen!=null && !pageLayouts.isEmpty() && !pageBitmaps.isEmpty();
        ZoomAnchor anchor=pdfZoomMotion.zooming()?zoomMotionAnchor:captureZoomAnchor(canvasPoint,viewportPoint);
        double baseline=pdfZoomMotion.zooming()?zoomMotionBasePercent:currentPdfZoomPercent();
        JComboBox<String> control=activePdfZoom();control.setPopupVisible(false);
        DefaultComboBoxModel<String> model=pdfZoomModel();
        if(model.getIndexOf(target)<0)model.addElement(target);
        model.setSelectedItem(target);
        // Publish a complete model with a valid selection in one step. Incremental
        // add/select/remove events can expose stale selection state to the renderer.
        updatingPdfZoom=true;
        try {control.setModel(model);}finally {updatingPdfZoom=false;}
        if(animate && anchor!=null)animatePdfZoom(percent,baseline,anchor);
        else renderPage(anchor);
    }

    private void animatePdfZoom(int percent,double baseline,ZoomAnchor anchor) {
        if(!pdfZoomMotion.zooming()) {
            zoomMotionBasePercent=baseline;
            zoomMotionAnchor=anchor;
            renderGeneration.incrementAndGet();
            pendingPages.clear();wantedPages=Set.of();
            scrollPageTimer.stop();
        }
        resizingPdf=true;
        Rectangle box=pageLayouts.get(anchor.page()-1).bounds();
        double x=box.x+anchor.xFraction()*box.width,y=box.y+anchor.yFraction()*box.height;
        PdfSource target=source;
        pdfZoomMotion.zoom(percent/zoomMotionBasePercent,x,y,()->{
            if(closed || source!=target)return;
            rebuildingViewer=true;
            pageLayouts.clear();layoutPdfPages(target);
            lastViewportWidth=pdfLayoutWidth();
            lastViewportHeight=imageScroll.getViewport().getHeight();
            resizingPdf=false;rebuildingViewer=false;
            restoreZoomAnchor(anchor);
            imageCanvas.repaint();
        });
    }

    private void zoomPdfWithWheel(java.awt.event.MouseWheelEvent event) {
        double rotation=event.getPreciseWheelRotation();
        long now=System.nanoTime();
        if(now-lastZoomWheelNanos>400_000_000L ||
            Math.signum(rotation)!=Math.signum(zoomWheelAccumulation))zoomWheelAccumulation=0;
        lastZoomWheelNanos=now;
        zoomWheelAccumulation+=rotation;
        if(Math.abs(zoomWheelAccumulation)<.45)return;
        changePdfZoomFine(zoomWheelAccumulation<0?1:-1,
            SwingUtilities.convertPoint(imageScroll,event.getPoint(),imageCanvas),
            SwingUtilities.convertPoint(imageScroll,event.getPoint(),imageScroll.getViewport()));
        zoomWheelAccumulation=0;
    }

    private void renderPage() {renderPage(null);}

    private void renderPage(ZoomAnchor requestedAnchor) {
        renderPage(requestedAnchor,null);
    }

    private void renderPage(ZoomAnchor requestedAnchor,Runnable restored) {
        ZoomAnchor anchor=panelLayoutAnchor!=null?panelLayoutAnchor:requestedAnchor;
        PdfSource target=source;if(target==null || closed)return;
        if(LayoutMotionPanel.defer(viewer,"pdf-render",()->renderPage(anchor,restored)))return;
        rebuildingViewer=true;
        resizingPdf=false;
        int version=renderGeneration.incrementAndGet();
        clearViewerImages();pageLayouts.clear();
        lastViewportWidth=pdfLayoutWidth();
        lastViewportHeight=imageScroll.getViewport().getHeight();
        layoutPdfPages(target);
        rebuildingViewer=false;
        SwingUtilities.invokeLater(()->{
            if(source==target && version==renderGeneration.get()) {
                if(anchor==null)scrollToPage(page);
                else restoreZoomAnchor(anchor);
                if(restored!=null)restored.run();
                refreshThumbnails();
            }
        });
    }

    private void finishPdfResize(ZoomAnchor anchor) {
        if(source==null || closed || pdfZoomMotion.zooming())return;
        // Preview and completion share one deferred slot: the last resize event wins.
        // A stale preview must never run after completion and leave rendering suspended.
        if(LayoutMotionPanel.defer(viewer,"pdf-layout",()->finishPdfResize(anchor)))return;
        resizingPdf=false;
        lastViewportHeight=imageScroll.getViewport().getHeight();
        if("너비 맞춤".equals(activePdfZoom().getSelectedItem()) &&
            Math.abs(pdfLayoutWidth()-lastViewportWidth)>8)renderPage(anchor);
        else if(anchor!=null)restoreZoomAnchor(anchor);
        else refreshVisiblePages();
    }

    private void previewPdfResize(ZoomAnchor anchor) {
        PdfSource target=source;if(target==null || closed)return;
        if(LayoutMotionPanel.defer(viewer,"pdf-layout",()->previewPdfResize(anchor)))return;
        scrollPageTimer.stop();
        resizingPdf=true;
        rebuildingViewer=true;
        pageLayouts.clear();
        layoutPdfPages(target);
        rebuildingViewer=false;
        if(anchor==null)scrollToPage(page);
        else restoreZoomAnchor(anchor);
        imageCanvas.repaint();
    }

    private int pdfLayoutWidth() {
        int width=imageScroll.getViewport().getWidth();
        if(!"너비 맞춤".equals(activePdfZoom().getSelectedItem()))return width;
        if("너비 맞춤".equals(activePdfZoom().getSelectedItem())) {
            // Reserve the same vertical gutter whether its thumb is visible or not.
            // Measuring the current viewport makes short documents alternate between
            // wider/taller (bar needed) and narrower/shorter (bar no longer needed).
            Insets outer=imageScroll.getInsets();
            Insets inner=imageScroll.getViewportBorder()==null?null:imageScroll.getViewportBorder().getBorderInsets(imageScroll);
            int gutter=imageScroll.getVerticalScrollBar().getPreferredSize().width;
            if(imageScroll.getWidth()>0)width=imageScroll.getWidth()-outer.left-outer.right-(inner==null?0:inner.left+inner.right);
            else if(imageScroll.getVerticalScrollBar().isVisible())width+=gutter;
            JViewport rowHeader=imageScroll.getRowHeader();
            if(rowHeader!=null && rowHeader.isVisible())width-=rowHeader.getPreferredSize().width;
            width-=gutter;
        }
        return Math.max(320,width);
    }

    private void layoutPdfPages(PdfSource target) {
        imageCanvas.remove(pageImage);
        int viewportWidth=Math.max(320,pdfLayoutWidth());
        String selected=(String)activePdfZoom().getSelectedItem();
        boolean fit="너비 맞춤".equals(selected);
        float zoomFactor=fit?1f:Float.parseFloat(selected.replace("%",""))/100f;
        int y=16,columnWidth=viewportWidth,thumbnailY=4;
        thumbnailLayouts.clear();
        for(int number=1;number<=target.count;number++) {
            Dimension size=target.pageSize(number);
            int thumbHeight=Math.max(1,Math.min(150,Math.round(THUMB_WIDTH*(float)size.height/size.width)));
            int thumbWidth=Math.max(1,Math.min(THUMB_WIDTH,Math.round(thumbHeight*(float)size.width/size.height)));
            thumbnailLayouts.add(new Rectangle((150-thumbWidth)/2,thumbnailY+4,thumbWidth,thumbHeight));
            thumbnailY+=thumbHeight+27;
            int width=fit?Math.max(240,viewportWidth-32):Math.max(120,Math.round(size.width*zoomFactor));
            int height=Math.max(1,Math.round(width*(float)size.height/size.width));
            columnWidth=Math.max(columnWidth,width+32);
            float qualityFactor=switch(pdfQuality) {
                case "저화질" -> .6f;
                case "고화질" -> 1.5f;
                default -> 1f;
            };
            float scale=Math.min(7.5f,Math.max(.25f,Math.min(width*1.5f/size.width,
                3500f/Math.max(size.width,size.height))*qualityFactor));
            pageLayouts.add(new PageLayout(number,new Rectangle(0,y,width,height),scale));
            y+=height+16;
        }
        for(PageLayout layout:pageLayouts) layout.bounds().x=(columnWidth-layout.bounds().width)/2;
        imageCanvas.setPreferredSize(new Dimension(columnWidth,Math.max(y,400)));
        thumbnailCanvas.setPreferredSize(new Dimension(150,thumbnailY));
        imageCanvas.revalidate();thumbnailCanvas.revalidate();
    }

    private void restoreZoomAnchor(ZoomAnchor requestedAnchor) {
        ZoomAnchor anchor=panelLayoutAnchor!=null?panelLayoutAnchor:requestedAnchor;
        if(anchor.page()<1 || anchor.page()>pageLayouts.size()) {scrollToPage(page);return;}
        Rectangle bounds=pageLayouts.get(anchor.page()-1).bounds();
        JViewport viewport=imageScroll.getViewport();
        // Negative viewport coordinates request centering using the destination viewport.
        int viewportX=anchor.viewportX()<0?viewport.getWidth()/2:anchor.viewportX();
        int viewportY=anchor.viewportY()<0?viewport.getHeight()/2:anchor.viewportY();
        int x=(int)Math.round(bounds.x+anchor.xFraction()*bounds.width-viewportX);
        int y=(int)Math.round(bounds.y+anchor.yFraction()*bounds.height-viewportY);
        int maxX=Math.max(0,imageCanvas.getPreferredSize().width-viewport.getWidth());
        int maxY=Math.max(0,imageCanvas.getPreferredSize().height-viewport.getHeight());
        programmaticScroll=true;
        try {
            viewport.setViewSize(imageCanvas.getPreferredSize());
            viewport.setViewPosition(new Point(Math.max(0,Math.min(maxX,x)),Math.max(0,Math.min(maxY,y))));
        }
        finally {programmaticScroll=false;}
        setCurrentPage(anchor.page());
        refreshVisiblePages();
    }

    private void scrollToPage(int number) {
        if(number<1 || number>pageLayouts.size())return;
        programmaticScroll=true;
        try {
            int y=Math.max(0,pageLayouts.get(number-1).bounds().y-16);
            int max=Math.max(0,imageCanvas.getPreferredSize().height-imageScroll.getViewport().getHeight());
            imageScroll.getViewport().setViewPosition(new Point(0,Math.min(y,max)));
        } finally {programmaticScroll=false;}
        refreshVisiblePages();
    }

    private void onPageViewportChanged() {
        if(rebuildingViewer || resizingPdf || source==null || pageLayouts.isEmpty())return;
        refreshVisiblePages();
        if(programmaticScroll || panelLayoutAnchor!=null || pendingLayoutAnchor!=null ||
            ("너비 맞춤".equals(activePdfZoom().getSelectedItem()) &&
             Math.abs(pdfLayoutWidth()-lastViewportWidth)>8))return;
        scrollPageTimer.setRepeats(false);
        scrollPageTimer.restart();
    }

    private void updatePageFromScroll() {
        if(rebuildingViewer || panelLayoutAnchor!=null || source==null || pageLayouts.isEmpty())return;
        Rectangle visible=imageScroll.getViewport().getViewRect();
        // The slide at the viewport center is the one being read, even when an earlier slide peeks in above.
        int focus=visible.y+Math.max(1,visible.height/2);
        for(PageLayout layout:pageLayouts) if(layout.bounds().y+layout.bounds().height>=focus) {
            setCurrentPage(layout.number());break;
        }
    }

    private void refreshVisiblePages() {
        if(LayoutMotionPanel.defer(viewer,"pdf-visible",this::refreshVisiblePages))return;
        PdfSource target=source;if(resizingPdf || target==null || pageLayouts.isEmpty())return;
        Rectangle visible=imageScroll.getViewport().getViewRect();if(visible.height<1)return;
        boolean movingDown=visible.y>=lastScrollY;
        lastScrollY=visible.y;
        int before=movingDown?visible.height/2:visible.height*2;
        int after=movingDown?visible.height*2:visible.height/2;
        int nearbyTop=Math.max(0,visible.y-before);
        Rectangle nearby=new Rectangle(0,nearbyTop,imageCanvas.getPreferredSize().width,
            visible.y+visible.height+after-nearbyTop);
        List<PageLayout> nearbyLayouts=PdfPageRange.within(pageLayouts,PageLayout::bounds,nearby);
        Set<Integer> wanted=new LinkedHashSet<>();
        Set<Integer> visiblePages=new HashSet<>();
        for(PageLayout layout:nearbyLayouts) if(visible.intersects(layout.bounds())){
            wanted.add(layout.number());visiblePages.add(layout.number());
        }
        if(movingDown) {
            for(PageLayout layout:nearbyLayouts)
                if(layout.bounds().y>=visible.y+visible.height && nearby.intersects(layout.bounds()))
                    wanted.add(layout.number());
        } else {
            for(int i=nearbyLayouts.size()-1;i>=0;i--) {
                PageLayout layout=nearbyLayouts.get(i);
                if(layout.bounds().y+layout.bounds().height<=visible.y && nearby.intersects(layout.bounds()))
                    wanted.add(layout.number());
            }
        }
        for(PageLayout layout:nearbyLayouts) if(nearby.intersects(layout.bounds()))wanted.add(layout.number());
        wantedPages=Set.copyOf(PdfBitmapBudget.select(wanted,visiblePages,number->{
            PageLayout layout=pageLayouts.get(number-1);Dimension size=target.pageSize(number);
            return (long)Math.min(Long.MAX_VALUE,4d*Math.ceil(size.width*layout.renderScale())*Math.ceil(size.height*layout.renderScale()));
        },PdfBitmapBudget.BYTES));
        trimCachedPages();
        int version=renderGeneration.get();
        for(int number:wanted) if(wantedPages.contains(number) &&
            (!pageBitmaps.containsKey(number) || Math.abs(pageBitmapScales.getOrDefault(number,0f)-pageLayouts.get(number-1).renderScale())>.001f)
            && pendingPages.add(number)) {
            PageLayout layout=pageLayouts.get(number-1);
            BufferedImage prior=pageBitmaps.get(number);
            boolean dissolve=pdfOnlyScreen!=null && prior!=null && visible.intersects(layout.bounds());
            renders.execute(()->{
                if(version!=renderGeneration.get())return;
                if(!wantedPages.contains(number)) {
                    SwingUtilities.invokeLater(()->{if(version==renderGeneration.get()){pendingPages.remove(number);refreshVisiblePages();}});
                    return;
                }
                try {
                    // Render and shrink the disposable preview off the EDT. No full-size duplicate/cache.
                    BufferedImage preview=dissolve?PdfZoomMotion.preview(prior):null;
                    BufferedImage bitmap;
                    try {bitmap=target.render(number,layout.renderScale());}
                    catch(Exception failure) {if(preview!=null)preview.flush();throw failure;}
                    SwingUtilities.invokeLater(()->{
                        if(version!=renderGeneration.get()) {bitmap.flush();if(preview!=null)preview.flush();return;}
                        pendingPages.remove(number);
                        if(closed || source!=target || !wantedPages.contains(number)) {bitmap.flush();if(preview!=null)preview.flush();return;}
                        BufferedImage replaced=pageBitmaps.put(number,bitmap);
                        pageBitmapScales.put(number,layout.renderScale());
                        if(replaced!=null)replaced.flush();
                        if(preview!=null)pdfZoomMotion.dissolve(number,preview);
                        trimCachedPages();
                        if(initialPdfEntrance&&imageScroll.getViewport().getViewRect().intersects(layout.bounds())) {
                            initialPdfEntrance=false;
                            LayoutMotionPanel.fadeInContent(viewer);
                        }
                        imageCanvas.repaint(layout.bounds());
                    });
                } catch(Exception failure) {SwingUtilities.invokeLater(()->{if(version==renderGeneration.get()){pendingPages.remove(number);imageCanvas.repaint(layout.bounds());}});}
            });
        }
    }

    private void trimCachedPages() {
        int limit=6;
        long bytes=pageBitmaps.values().stream().mapToLong(image->4L*image.getWidth()*image.getHeight()).sum();
        if(pageBitmaps.size()<=limit&&bytes<=PdfBitmapBudget.BYTES)return;
        Rectangle visible=imageScroll.getViewport().getViewRect();
        int focus=visible.y+visible.height/2;
        while(pageBitmaps.size()>limit || bytes>PdfBitmapBudget.BYTES) {
            int farthest=-1,distance=-1;
            for(int number:pageBitmaps.keySet()) {
                if(wantedPages.contains(number))continue;
                Rectangle bounds=pageLayouts.get(number-1).bounds();
                int gap=Math.abs(bounds.y+bounds.height/2-focus);
                if(gap>distance) {distance=gap;farthest=number;}
            }
            if(farthest<0)break;
            BufferedImage removed=pageBitmaps.remove(farthest);
            pageBitmapScales.remove(farthest);pdfZoomMotion.remove(farthest);
            bytes-=4L*removed.getWidth()*removed.getHeight();removed.flush();
        }
    }

    private void repaintPageOutline(int number) {
        if(number<1||number>pageLayouts.size())return;
        Rectangle box=pageLayouts.get(number-1).bounds();
        int x=box.x-4,y=box.y-4,w=box.width+8,h=box.height+8;
        // Only the old/new perimeter changes when the current page changes.
        imageCanvas.repaint(x,y,w,8);imageCanvas.repaint(x,y+h-8,w,8);
        imageCanvas.repaint(x,y,8,h);imageCanvas.repaint(x+w-8,y,8,h);
    }

    private void paintPdfPages(Graphics graphics) {
        if(source==null)return;
        Graphics2D g=(Graphics2D)graphics.create();
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        pdfZoomMotion.transform(g);
        Rectangle clip=g.getClipBounds();
        for(PageLayout layout:pageLayouts) {
            Rectangle box=layout.bounds();if(clip!=null && !clip.intersects(box.x-4,box.y-4,box.width+8,box.height+8))continue;
            g.setColor(Color.WHITE);g.fillRect(box.x,box.y,box.width,box.height);
            BufferedImage bitmap=pageBitmaps.get(layout.number());
            if(bitmap!=null)pdfZoomMotion.paint(g,layout.number(),bitmap,box);
            else {g.setColor(MUTED);g.drawString("p."+layout.number()+" 표시 중…",box.x+18,box.y+28);}
            if(textSelection.hasSelection() && index!=null) {
                g.setColor(new Color(72, 117, 240, 90));
                for(PdfTextSelection.Word word:textSelection.words(index,layout.number()))
                    if(textSelection.selected(word)) {
                        Rectangle selectedBox=word.bounds(box);
                        g.fillRect(selectedBox.x,selectedBox.y,selectedBox.width,selectedBox.height);
                    }
            }
            g.setStroke(new BasicStroke(1));
            g.setColor(new Color(0xd8e5f5));g.drawRect(box.x,box.y,box.width,box.height);
            if(layout.number()==page) {
                // Two native strokes, without blur, extra bitmaps, or PDF re-rendering.
                g.setColor(new Color(0,0,0,22));g.setStroke(new BasicStroke(5));
                g.drawRect(box.x-1,box.y-1,box.width+2,box.height+2);
                g.setColor(Color.BLACK);g.setStroke(new BasicStroke(1.5f));
                g.drawRect(box.x-2,box.y-2,box.width+4,box.height+4);
                g.setStroke(new BasicStroke(1));
            }
            if(selectingImage && layout.number()==selectionPage && index!=null) {
                JsonObject selected=index.getAsJsonArray("pages").get(selectionPage-1).getAsJsonObject();
                if(selected.has("imageRegions")) for(JsonElement item:selected.getAsJsonArray("imageRegions")) {
                    JsonArray b=item.getAsJsonObject().getAsJsonArray("bbox");
                    int x=box.x+Math.round(b.get(0).getAsFloat()*box.width),y=box.y+Math.round(b.get(1).getAsFloat()*box.height);
                    int w=Math.round((b.get(2).getAsFloat()-b.get(0).getAsFloat())*box.width);
                    int h=Math.round((b.get(3).getAsFloat()-b.get(1).getAsFloat())*box.height);
                    g.setColor(new Color(84,119,236,45));g.fillRect(x,y,w,h);
                    g.setColor(BLUE);g.setStroke(new BasicStroke(2));g.drawRect(x,y,w,h);
                }
            }
        }
        g.dispose();
    }

    private PageLayout textPageAt(Point point, boolean insidePage) {
        PageLayout nearest=null;
        int distance=Integer.MAX_VALUE;
        for(PageLayout layout:pageLayouts) {
            Rectangle box=layout.bounds();
            if(box.contains(point))return layout;
            if(insidePage)continue;
            int gap=point.y<box.y?box.y-point.y:Math.max(0,point.y-box.y-box.height);
            if(gap<distance) {distance=gap;nearest=layout;}
        }
        return nearest;
    }

    private void copySelectedPdfText() {
        String text=textSelection.text(index);
        if(text.isBlank())return;
        try {
            Toolkit.getDefaultToolkit().getSystemClipboard().setContents(new StringSelection(text),null);
            status.setText("선택한 PDF 텍스트를 복사했습니다.");
        } catch(IllegalStateException failure) {
            status.setText("클립보드를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.");
        }
    }

    private void showPdfTextMenu(java.awt.event.MouseEvent event) {
        if(!textSelection.hasSelection())return;
        JPopupMenu menu=new JPopupMenu();
        JMenuItem copy=new JMenuItem("선택한 텍스트 복사");
        copy.addActionListener(e->copySelectedPdfText());
        menu.add(copy);menu.show(imageCanvas,event.getX(),event.getY());
    }

    private void refreshThumbnails() {
        PdfSource target=source;if(target==null || thumbnailLayouts.isEmpty() || !thumbnailScroll.isVisible())return;
        Rectangle visible=thumbnailScroll.getViewport().getViewRect();if(visible.height<1)return;
        int first=Math.max(1,thumbnailPageAt(visible.y)-1),last=Math.min(target.count,thumbnailPageAt(visible.y+visible.height)+2);
        Set<Integer> wanted=new LinkedHashSet<>();for(int number=first;number<=last;number++)wanted.add(number);
        wantedThumbnails=Set.copyOf(wanted);
        thumbnailBitmaps.entrySet().removeIf(entry->{if(wanted.contains(entry.getKey()))return false;entry.getValue().flush();return true;});
        thumbnailCanvas.repaint();
        int version=renderGeneration.get();
        for(int number:wanted) if(!thumbnailBitmaps.containsKey(number) && pendingThumbnails.add(number)) {
            Dimension size=target.pageSize(number);
            float scale=Math.min(.5f,THUMB_WIDTH*1.2f/size.width);
            renders.execute(()->{
                if(version!=renderGeneration.get())return;
                if(!wantedThumbnails.contains(number)) {
                    SwingUtilities.invokeLater(()->{if(version==renderGeneration.get()){pendingThumbnails.remove(number);refreshThumbnails();}});
                    return;
                }
                try {
                    BufferedImage bitmap=target.render(number,scale);
                    SwingUtilities.invokeLater(()->{
                        if(version!=renderGeneration.get()) {bitmap.flush();return;}
                        pendingThumbnails.remove(number);
                        if(closed || source!=target || !wantedThumbnails.contains(number)) {bitmap.flush();return;}
                        thumbnailBitmaps.put(number,bitmap);thumbnailCanvas.repaint();
                    });
                } catch(Exception failure) {SwingUtilities.invokeLater(()->{if(version==renderGeneration.get()){pendingThumbnails.remove(number);thumbnailCanvas.repaint();}});}
            });
        }
    }

    /** Page rows follow the actual PDF aspect ratio; painting, clicks and lazy loading share these bounds. */
    private int thumbnailPageAt(int y) {
        int low=0,high=thumbnailLayouts.size()-1;
        while(low<=high){int mid=(low+high)>>>1;if(y<thumbnailLayouts.get(mid).y-4)high=mid-1;else low=mid+1;}
        return Math.max(1,Math.min(thumbnailLayouts.size(),high+1));
    }

    private void paintThumbnails(Graphics graphics) {
        PdfSource target=source;if(target==null || thumbnailLayouts.isEmpty())return;
        Graphics2D g=(Graphics2D)graphics.create();
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        Rectangle clip=g.getClipBounds();
        int first=clip==null?1:thumbnailPageAt(clip.y);
        int last=clip==null?target.count:Math.min(target.count,thumbnailPageAt(clip.y+clip.height)+1);
        for(int number=first;number<=last;number++) {
            Rectangle bounds=thumbnailLayouts.get(number-1);
            g.setColor(number==page?StudyTheme.ACCENT_SOFT:MistWorkspaceTheme.SOFT);g.fillRect(5,bounds.y-4,140,bounds.height+23);
            BufferedImage bitmap=thumbnailBitmaps.get(number);
            g.setColor(Color.WHITE);g.fillRect(bounds.x,bounds.y,bounds.width,bounds.height);
            if(bitmap!=null)g.drawImage(bitmap,bounds.x,bounds.y,bounds.width,bounds.height,null);
            g.setColor(number==page?BLUE:MistWorkspaceTheme.LINE);g.drawRect(bounds.x,bounds.y,bounds.width,bounds.height);
            String label=Integer.toString(number);g.setColor(INK);
            g.drawString(label,(150-g.getFontMetrics().stringWidth(label))/2,bounds.y+bounds.height+15);
        }
        g.dispose();
    }

    private void clearViewerImages() {
        pdfZoomMotion.clear();pageBitmapScales.clear();
        for(BufferedImage image:pageBitmaps.values())image.flush();
        for(BufferedImage image:thumbnailBitmaps.values())image.flush();
        pageBitmaps.clear();thumbnailBitmaps.clear();pendingPages.clear();pendingThumbnails.clear();
        wantedPages=Set.of();wantedThumbnails=Set.of();
    }

    private void updateOriginal() {
        originalDirty=true;
        if(sourceTabs.getSelectedIndex()!=1)return;
        originalDirty=false;
        if(index==null) {original.setText(documentHtml("추출 원문","원문 준비 중…")); return;}
        JsonObject p=index.getAsJsonArray("pages").get(page-1).getAsJsonObject();
        StringBuilder body=new StringBuilder("<p class='muted'>실제 PDF "+page+"쪽 · 페이지 라벨 "+escape(str(p,"label"))+"</p>");
        body.append("<p class='muted'>PDF 텍스트 직접 추출 · 로컬 OCR 사용 안 함</p>");
        JsonObject fontRepair=p.has("fontRepair")&&p.get("fontRepair").isJsonObject()?p.getAsJsonObject("fontRepair"):null;
        boolean fontRepaired=fontRepair!=null&&fontRepair.has("replacedGlyphs")&&fontRepair.get("replacedGlyphs").getAsInt()>0;
        if(fontRepaired)body.append("<p class='warning'>수식 폰트의 깨진 문자 ")
            .append(fontRepair.get("replacedGlyphs").getAsInt())
            .append("개를 복원했습니다. 분수·첨자·큰 괄호의 배치는 PDF 원본이나 AI 페이지 판독과 대조해 주세요.</p>");
        if(str(p,"status").equals("failed"))body.append("<p>텍스트 추출 실패 · 페이지 전체 분석으로 확인할 수 있습니다.</p>");
        if(fontRepaired)body.append(pageAnalysisHtml(p));
        if(!str(p,"nativeText").isBlank())body.append(fontRepaired?"<h3>복원한 PDF 텍스트</h3><pre>":"<h3>PDF 텍스트</h3><pre>").append(escape(str(p,"nativeText"))).append("</pre>");
        if(!fontRepaired)body.append(pageAnalysisHtml(p));
        if(!p.has("pageAnalysis")) {
            JsonObject old=visualResult(source,page);
            if(old!=null)body.append("<h3>이전 AI 해석 · 보관된 결과</h3>").append(StudyMarkdown.render(str(old,"description"),14));
        }
        original.setText(documentHtml("추출 원문",body.toString())); original.setCaretPosition(0);
    }

    static String pageAnalysisHtml(JsonObject page) {
        int number=page.get("number").getAsInt();
        if(!page.has("pageAnalysis"))return "<p>PDF "+number+"쪽 · 페이지 AI 분석 대기</p>";
        JsonObject analysis=page.getAsJsonObject("pageAnalysis");
        StringBuilder body=new StringBuilder("<h3>PDF "+number+"쪽 · AI 페이지 판독</h3><p>"+
            ("ready".equals(str(analysis,"status"))?"분석 결과 준비됨 · 원본과 대조 가능":"일부 요소 확인 필요 · 자동 재호출하지 않음")+"</p>");
        for(JsonElement item:analysis.getAsJsonArray("elements")) {
            JsonObject e=item.getAsJsonObject();if("decoration".equals(str(e,"kind")))continue;
            body.append("<h4>").append(escape(str(e,"title"))).append("</h4>");
            body.append(StudyMarkdown.render(str(e,"transcription"),14));
            for(JsonElement f:e.getAsJsonArray("formulas")) {
                JsonObject formula=f.getAsJsonObject();
                body.append(StudyMarkdown.render("$$\n"+str(formula,"latex")+"\n$$",14));
                if(!str(formula,"uncertainSymbols").isBlank())body.append("<p>판독 확인 필요: ").append(escape(str(formula,"uncertainSymbols"))).append("</p>");
            }
            body.append(StudyMarkdown.render(str(e,"description"),14));
            for(JsonElement r:e.getAsJsonArray("relationships"))body.append(StudyMarkdown.render(r.getAsString(),14));
            if(!str(e,"purpose").isBlank())body.append("<p><b>맥락에 따른 해석:</b> ").append(escape(str(e,"purpose"))).append("</p>");
            for(JsonElement issue:e.getAsJsonArray("uncertainDetails"))body.append("<p>확인 필요: ").append(escape(issue.getAsString())).append("</p>");
        }
        return body.toString();
    }

    private void searchOriginal() {
        searchItems.clear(); if(index==null) return;
        String needle=search.getText().strip().toLowerCase(Locale.ROOT); if(needle.isEmpty()) return;
        for(JsonElement value:index.getAsJsonArray("chunks")) {
            JsonObject chunk=value.getAsJsonObject(); if(str(chunk,"text").toLowerCase(Locale.ROOT).contains(needle)) searchItems.addElement(chunk);
            if(searchItems.size()>=300) break;
        }
        if(searchItems.isEmpty()) status.setText("검색 결과 없음 · 페이지 분석 상태와 표현 차이를 확인하세요");
        else status.setText("원문 검색 "+searchItems.size()+"건 · 결과를 누르면 해당 위치로 이동합니다");
    }

    private void renderSummary() { renderSummary(false); }
    private boolean deferStudyView(JComponent view) {
        return (studyViewsWereVisible||isDisplayable())&&!view.isShowing();
    }
    private boolean deferSummaryRender() {
        if(!deferStudyView(summaryScroll))return false;
        summaryRenderPending=true;return true;
    }
    private void refreshPendingStudyViews() {
        if(closed)return;
        if(summaryRenderPending&&summaryScroll.isShowing())renderSummary(true);
        if(conceptRenderPending&&conceptOverview.isShowing())showConcepts(true);
    }
    private void interruptSummaryFade() {if(summaryFadeAlpha>0 || pendingSavedSummaryFade)clearSummaryFade();}
    private void clearSummaryFade() {
        if(summaryFadeTimer!=null) {summaryFadeTimer.stop();summaryFadeTimer=null;}
        pendingSavedSummaryFade=false;
        summaryFadeAlpha=0;
        summaryFadeSnapshot=null;
        summaryFadeLayer.setLayerEventMask(0);
        summaryFadeLayer.repaint();
    }
    private void fadeInSavedSummary() {
        clearSummaryFade();
        pendingSavedSummaryFade=true;
        SwingUtilities.invokeLater(this::startPendingSavedSummaryFade);
    }
    private void startPendingSavedSummaryFade() {
        if(!pendingSavedSummaryFade || !summaryFadeLayer.isShowing() || summaryFadeLayer.getWidth()<=0)return;
        pendingSavedSummaryFade=false;
        summaryFadeLayer.setLayerEventMask(AWTEvent.MOUSE_EVENT_MASK|AWTEvent.MOUSE_MOTION_EVENT_MASK
            |AWTEvent.MOUSE_WHEEL_EVENT_MASK|AWTEvent.KEY_EVENT_MASK);
        summaryFadeAlpha=1f;
        summaryFadeLayer.repaint();
        long started=System.nanoTime();
        summaryFadeTimer=new javax.swing.Timer(16,event->{
            float fraction=(float)Math.min(1,(System.nanoTime()-started)/168_000_000d);
            summaryFadeAlpha=1f-fraction;
            summaryFadeLayer.repaint();
            if(fraction>=1f) {
                ((javax.swing.Timer)event.getSource()).stop();
                summaryFadeTimer=null;
                summaryFadeSnapshot=null;
                summaryFadeLayer.setLayerEventMask(0);
            }
        });
        summaryFadeTimer.start();
    }
    private void renderSummary(boolean preserveScroll) {
        if(deferSummaryRender())return;
        summaryRenderPending=false;
        if(LayoutMotionPanel.defer(summaryScroll,"summary",()->renderSummary(preserveScroll)))return;
        if(source==null) return;
        if(generated==null || liveGenerationKey!=null)clearSummaryFade();
        String selectedScope=switch(scope.getSelectedIndex()){case 1->"page";case 2->"section";default->"document";};
        if(liveGenerationKey!=null && liveGenerationKey.equals(productKey(selectedScope,page))) {
            renderLiveSummary();return;
        }
        OutlineAnchor outlineAnchor=preserveScroll?captureSummaryOutlineAnchor():null;
        summarySelectionSources.clear();summaryOutlineEntries=List.of();
        StringBuilder body=new StringBuilder();
        Map<String,SlideLens.Request> modules=new LinkedHashMap<>();
        summaryStepFlows.clear();
        if(generated!=null) {
            boolean partial=str(generated,"kind").equals("partial");
            boolean progressOverview=partial && summaryActivity.state()!=SummaryActivityBar.State.IDLE
                && generated.has("overview") && generated.get("overview").isJsonObject()
                && !str(generated.getAsJsonObject("overview"),"body").isBlank();
            if(summaryActivity.state()!=SummaryActivityBar.State.IDLE && !progressOverview)body.append(summaryActivityHeader());
            if(generated.has("coverageCounts")) {
                JsonObject counts=generated.getAsJsonObject("coverageCounts");
                body.append("<p class='muted'>원문 블록 · 강의 해설 반영 ").append(counts.get("summarized").getAsInt())
                    .append(" · 반복 통합 ").append(counts.get("integrated").getAsInt())
                    .append(" · 제외 ").append(counts.get("excluded").getAsInt())
                    .append(" · 확인 필요 ").append(counts.get("needs_review").getAsInt())
                    .append(" · 강의 해설 대기 ").append(counts.get("pending_summary").getAsInt()).append("</p>");
            }
            String easyPrefix=productKey(str(generated,"scope"),generated.get("page").getAsInt());
            List<JsonObject> visibleSections=new ArrayList<>();
            for(JsonElement item:generated.getAsJsonArray("sections")) {
                JsonObject section=item.getAsJsonObject();
                if(!isEmptyStudyPlaceholder(section))visibleSections.add(section);
            }
            boolean hasSections=partial || visibleSections.size()>1
                || (isRegionStrategy(str(generated,"strategy")) && !visibleSections.isEmpty());
            boolean completedOverview=summaryReadingSkin && !partial && summaryActivity.state()==SummaryActivityBar.State.IDLE;
            if(completedOverview || progressOverview) {
                body.append(progressOverview?"<!--LIVEOVERVIEWSTART-->":"<!--OVERVIEWSTART-->");
                if(!hasSections)body.append("<a name='synesis-summary-content'></a>");
                body.append(summaryBlock(generated.getAsJsonObject("overview"),easyPrefix+"/overview",false,modules));
                body.append("<!--OVERVIEWEND-->");
            } else if(partial || summaryActivity.state()==SummaryActivityBar.State.IDLE) {
                if(summaryReadingSkin && hasSections)body.append("<div class='study-overview'>");
                if(hasSections && !partial)body.append("<h2>").append(scope.getSelectedIndex()==0?"이 강의의 흐름":scope.getSelectedIndex()==1?"이 페이지의 핵심":"이 범위의 흐름").append("</h2>");
                if(!hasSections)body.append("<a name='synesis-summary-content'></a>");
                body.append(summaryBlock(generated.getAsJsonObject("overview"),easyPrefix+"/overview",!hasSections,modules));
                if(summaryReadingSkin && hasSections)body.append("</div>");
            }
            if(hasSections && !visibleSections.isEmpty()) {
                summaryOutlineEntries=SummaryOutline.entries(generated);
                body.append(summaryHierarchy(summaryOutlineEntries,easyPrefix,modules));
            }
        } else {
            summaryOutlineEntries=List.of();
            if(summaryActivity.state()!=SummaryActivityBar.State.IDLE)body.append(summaryActivityHeader());
            else if(!automaticStudy)body.append("<p>강의 해설·개념 정리를 생성하면 이곳에 표시돼요.</p>");
            else if(scope.getSelectedIndex()==0)body.append("<p>강의 해설을 준비하고 있어요.</p>");
            else body.append("<p>이 범위에 저장된 강의 해설이 없어요. 전체 자료를 선택해 주세요.</p>");
        }
        int scrollY=preserveScroll?summaryScroll.getViewport().getViewPosition().y:0;
        long interaction=summaryScrollInteraction;
        renderSummaryContent(body.toString(),modules);
        refreshSummaryOutlineTree();
        restoreSummaryScroll(scrollY,false,interaction,outlineAnchor);
    }

    private SlideLens.Request validatedSlideLens(JsonObject block) {
        JsonObject value=block.has("slideLens") && block.get("slideLens").isJsonObject()
            ? block.getAsJsonObject("slideLens") : null;
        SlideLens.Request request=SlideLens.resolve(value,index);
        return request!=null && moduleHasEvidence(block,request.page())?request:null;
    }

    private void renderLiveSummary() {
        summarySelectionSources.clear();
        int oldY=summaryScroll.getViewport().getViewPosition().y;
        int previousMax=summaryScroll.getViewport().getViewSize().height-summaryScroll.getViewport().getExtentSize().height;
        boolean firstSummary=!summaryOverviewLoading.hasSummary() && hasLiveSummaryContent();
        boolean followEnd=!firstSummary && oldY>=Math.max(0,previousMax-3);
        OutlineAnchor outlineAnchor=followEnd?null:captureSummaryOutlineAnchor();
        long interaction=summaryScrollInteraction;
        summaryStepFlows.clear();
        Map<String,SlideLens.Request> modules=new LinkedHashMap<>();
        StringBuilder body=new StringBuilder();
        if(liveOverview!=null && !str(liveOverview,"body").isBlank()) {
            body.append("<!--LIVEOVERVIEWSTART-->");
            body.append(summaryBlock(liveOverview,liveGenerationKey+"/overview",false,modules));
            body.append("<!--OVERVIEWEND-->");
        } else body.append(summaryActivityHeader());
        if(!liveSummaryDrafts.isEmpty() || liveSummarySections.values().stream().anyMatch(s->s.has("hierarchy"))) {
            reconcileLiveSummarySpaces();
            Map<Integer,JsonObject> visible=new TreeMap<>();
            liveSummarySections.forEach((number,section)->{
                JsonObject display=section.deepCopy();
                if(liveSummarySpaces.containsKey(number)) {
                    JsonArray parts=display.has("parts")&&display.get("parts").isJsonArray()?display.getAsJsonArray("parts"):null;
                    JsonObject tail=parts!=null&&!parts.isEmpty()?parts.get(parts.size()-1).getAsJsonObject():display;
                    tail.addProperty("_liveSummarySpace",number);
                }
                visible.put(number,display);
            });
            liveSummaryDrafts.forEach((number,draft)->visible.putIfAbsent(number,streamingSection(number,draft)));
            summaryOutlineEntries=SummaryOutline.live(visible.values());
            body.append(summaryHierarchy(summaryOutlineEntries,liveGenerationKey,modules));
            renderSummaryContent(body.toString(),modules);refreshSummaryOutlineTree();
            restoreSummaryScroll(oldY,followEnd,interaction,outlineAnchor);startLiveSummaryMotion();return;
        }
        int sectionNumber=0;
        for(Map.Entry<Integer,JsonObject> entry:liveSummarySections.entrySet()) {
            JsonObject section=entry.getValue();String content=str(section,"body");
            if(isEmptyStudyPlaceholder(section))continue;
            String sectionKey=liveGenerationKey+"/section-"+(sectionNumber++);
            int total=content.codePointCount(0,content.length());
            int visible=Math.min(total,liveSummaryVisible.getOrDefault(entry.getKey(),0));
            TutorStreamFade fade=liveSummaryFades.get(entry.getKey());
            if(visible<total || fade!=null && fade.active(System.currentTimeMillis())) {
                body.append("<h3>").append(escape(str(section,"title"))).append("</h3>");
                String shown=content.substring(0,content.offsetByCodePoints(0,visible));
                String paragraph="<p>"+escape(shown)+"</p>";
                body.append(fade==null?paragraph:fade.decorate(paragraph,System.currentTimeMillis()));
                if(visible<total)body.append("<p class='muted'>▌</p>");
            } else {
                body.append(summaryBlock(section,sectionKey,true,modules));
            }
        }
        renderSummaryContent(body.toString(),modules);
        restoreSummaryScroll(oldY,followEnd,interaction);
    }

    private String summaryActivityHeader() {
        return "<!--SUMMARYACTIVITY-->";
    }
    private boolean hasLiveSummaryContent() {
        return liveOverview!=null && !str(liveOverview,"body").isBlank()
            || liveSummaryDrafts.values().stream().anyMatch(section->!str(section,"body").isBlank())
            || liveSummarySections.values().stream().anyMatch(section->!isEmptyStudyPlaceholder(section)
            && (!str(section,"body").isBlank() || section.has("parts") && section.get("parts").isJsonArray()
                && !section.getAsJsonArray("parts").isEmpty()));
    }
    private void setSummaryActivity(SummaryActivityBar.State state) {
        if(summaryActivity.state()==state)return;
        summaryActivity.setState(state);
        if(automaticStudy)updateAutomaticStudyControls();
        summaryOverviewLoading.update(state,summaryFontSize.getValue(),false);
        if(source!=null&&!closed)renderSummary(true);
    }
    private void configureSummaryPane(JEditorPane pane) {
        if(pane.getCaret() instanceof javax.swing.text.DefaultCaret caret)
            caret.setUpdatePolicy(javax.swing.text.DefaultCaret.NEVER_UPDATE);
        pane.addKeyListener(new java.awt.event.KeyAdapter(){
            @Override public void keyPressed(java.awt.event.KeyEvent e){summaryScrollInteraction++;}
        });
        pane.addMouseListener(new java.awt.event.MouseAdapter(){
            @Override public void mousePressed(java.awt.event.MouseEvent e){summaryScrollInteraction++;}
        });
        pane.addMouseMotionListener(new java.awt.event.MouseMotionAdapter(){
            @Override public void mouseDragged(java.awt.event.MouseEvent e){summaryScrollInteraction++;}
        });
    }
    private void restoreSummaryScroll(int y,boolean followEnd,long interaction) {
        restoreSummaryScroll(y,followEnd,interaction,null);
    }
    private void restoreSummaryScroll(int y,boolean followEnd,long interaction,OutlineAnchor anchor) {
        ++summaryScrollRequest;
        // Finish layout and anchoring in this EDT update. A queued correction can
        // otherwise paint the intermediate position or race the next wheel input.
        if(closed||interaction!=summaryScrollInteraction)return;
        restoringSummaryScroll=true;
        try {
            JViewport viewport=summaryScroll.getViewport();
            if(viewport.getView()!=summaryFlow)return;
            // Scrollbar bounds can lag a document update. Use the measured
            // content size instead of a stale maximum.
            Dimension size=summaryFlow.getPreferredSize();viewport.setViewSize(size);summaryFlow.doLayout();
            int max=Math.max(0,size.height-viewport.getExtentSize().height);
            int destination=y;
            if(!followEnd&&anchor!=null) {
                SummaryOutline.Target target=summaryTargets().get(anchor.id());
                Integer at=summaryOutlineY(target);if(at!=null)destination=at+anchor.offset();
            }
            viewport.setViewPosition(new Point(viewport.getViewPosition().x,followEnd?max:Math.max(0,Math.min(destination,max))));
        }
        finally {restoringSummaryScroll=false;}
    }

    private SummaryStreamSpace newSummaryStreamSpace(){
        SummaryStreamSpace space=new SummaryStreamSpace();space.pause(summaryScrollActivity.active());return space;
    }
    private void summaryScrollActivityChanged(boolean active){
        liveSummarySpaces.values().forEach(space->space.pause(active));
        if(!active&&!closed&&liveGenerationKey!=null)startLiveSummaryMotion();
    }

    private JsonObject streamingSection(int number,JsonObject draft) {
        String id="streaming-unit-"+number,title=str(draft,"title");
        if(title.isBlank())title="강의 해설 생성 중";
        int first=1;
        if(draft.has("visualPages")&&draft.get("visualPages").isJsonArray())
            for(JsonElement value:draft.getAsJsonArray("visualPages"))try {
                int candidate=value.getAsInt();if(source!=null&&candidate>=1&&candidate<=source.count){first=candidate;break;}
            }catch(RuntimeException ignored){}
        JsonArray pages=new JsonArray();pages.add(first);
        JsonObject part=new JsonObject();part.addProperty("nodeId",id);part.addProperty("contentId",id+"/body");
        part.addProperty("title",title);part.addProperty("body",str(draft,"body"));
        part.addProperty("_liveSummaryUnit",number);part.add("visualPages",pages);
        JsonObject node=new JsonObject();node.addProperty("id",id);node.addProperty("parentId","");
        node.addProperty("title",title);node.addProperty("page",first);node.addProperty("endPage",first);
        JsonArray nodes=new JsonArray();nodes.add(node);JsonObject hierarchy=new JsonObject();hierarchy.add("nodes",nodes);
        JsonArray parts=new JsonArray();parts.add(part);JsonObject section=draft.deepCopy();
        section.add("parts",parts);section.add("hierarchy",hierarchy);return section;
    }
    private JEditorPane streamingSummaryPane(int number,JsonObject draft,int fontSize) {
        JEditorPane pane=liveSummaryDraftPanes.computeIfAbsent(number,ignored->{
            StudyHtmlPane created=new StudyHtmlPane(true);configureSummaryPane(created);
            new SummaryStreamText(created);return created;
        });
        // The JSON/Markdown can end mid-escape or mid-equation. Preview only
        // decoded text; final validation supplies the formatted rich content.
        pane.putClientProperty("synesis.summaryStreamSpace",liveSummarySpaces.computeIfAbsent(number,ignored->newSummaryStreamSpace()));
        SummaryStreamText.of(pane).accept(str(draft,"body"),str(draft,"title"),fontSize);return pane;
    }
    private java.util.List<JEditorPane> liveStreamPanes() {
        java.util.List<JEditorPane> panes=new ArrayList<>(liveSummaryDraftPanes.values());
        if(liveOverviewStreamPane!=null)panes.add(liveOverviewStreamPane);
        return panes;
    }
    private JEditorPane streamingOverviewPane(int fontSize) {
        if(liveOverviewStreamPane==null) {
            StudyHtmlPane pane=new StudyHtmlPane(true);configureSummaryPane(pane);
            new SummaryStreamText(pane);pane.setOpaque(false);liveOverviewStreamPane=pane;
        }
        SummaryStreamText.of(liveOverviewStreamPane).accept(str(liveOverview,"body"),"",fontSize);
        return liveOverviewStreamPane;
    }
    private void reconcileLiveSummarySpaces() {
        SortedSet<Integer> visible=new TreeSet<>(liveSummarySections.keySet());visible.addAll(liveSummaryDrafts.keySet());
        liveSummarySpaces.keySet().retainAll(visible);
        for(int number:visible) {
            if(liveSummaryDiscarded.contains(number))continue;
            JsonObject section=liveSummarySections.get(number);
            if(section!=null&&isEmptyStudyPlaceholder(section))continue;
            Integer next=visible.tailSet(number+1).isEmpty()?null:visible.tailSet(number+1).first();
            boolean missing=next!=null?next>number+1:liveSummaryTotal>number;
            liveSummarySpaces.computeIfAbsent(number,ignored->newSummaryStreamSpace())
                .configure(liveSummaryDrafts.containsKey(number),missing,summaryFontSize.getValue());
        }
    }
    private void startLiveSummaryMotion() {
        if(liveGenerationKey==null||closed)return;
        if(!summaryFlow.isShowing()) {
            liveSummarySpaces.values().forEach(SummaryStreamSpace::settle);
            liveStreamPanes().forEach(p->{SummaryStreamText text=SummaryStreamText.of(p);if(text!=null)text.finish();});
            return;
        }
        if(liveSummaryMotionTimer==null) {
            liveSummaryMotionTimer=new javax.swing.Timer(16,event->advanceLiveSummaryMotion());
            liveSummaryMotionTimer.setCoalesce(true);
        }
        if(!liveSummaryMotionTimer.isRunning())liveSummaryMotionTimer.start();
    }
    private void advanceLiveSummaryMotion() {
        if(closed||liveGenerationKey==null||!summaryFlow.isShowing()) {
            if(liveSummaryMotionTimer!=null)liveSummaryMotionTimer.stop();
            liveSummarySpaces.values().forEach(SummaryStreamSpace::settle);
            liveStreamPanes().forEach(p->{SummaryStreamText text=SummaryStreamText.of(p);if(text!=null)text.finish();});
            completeLiveSummaryIfReady();return;
        }
        int oldY=summaryScroll.getViewport().getViewPosition().y;
        int previousMax=summaryScroll.getViewport().getViewSize().height-summaryScroll.getViewport().getExtentSize().height;
        boolean followEnd=oldY>=Math.max(0,previousMax-3);
        long interaction=summaryScrollInteraction;OutlineAnchor anchor=null;
        boolean geometry=false,active=false;long now=System.nanoTime();
        for(SummaryStreamSpace space:liveSummarySpaces.values()) {
            if(space.moving()&&!space.paused()&&anchor==null&&!followEnd)anchor=captureSummaryOutlineAnchor();
            geometry|=space.tick(now);active|=space.moving()&&!space.paused();
        }
        for(JEditorPane pane:liveStreamPanes()) {
            SummaryStreamText text=SummaryStreamText.of(pane);if(text==null)continue;
            if(pane.isShowing()&&!pane.getVisibleRect().isEmpty()) {
                text.repaintRecent(now);active|=text.active(now);
            }else text.finish();
        }
        if(geometry){summaryOutlineOffsets.clear();summaryFlow.revalidate();restoreSummaryScroll(oldY,followEnd,interaction,anchor);}
        if(!active&&liveSummaryMotionTimer!=null)liveSummaryMotionTimer.stop();
        completeLiveSummaryIfReady();
    }
    private void finishLiveSummaryMotion() {
        liveSummarySpaces.values().forEach(SummaryStreamSpace::finish);startLiveSummaryMotion();
    }
    private void completeLiveSummaryIfReady() {
        if(liveSummaryCompletion!=null&&!liveSummaryTyping()) {
            Runnable complete=liveSummaryCompletion;liveSummaryCompletion=null;complete.run();
        }
    }
    private void refreshStreamingSummary() {
        if(deferSummaryRender())return;
        // First received text is immediate. Later token bursts update only the
        // separate draft pane at most 10 times/sec; no concept rebuild per token.
        if(liveSummaryDraftPanes.isEmpty()&&!liveSummaryDrafts.isEmpty()) {renderSummary(true);liveSummaryDraftStructureDirty=false;return;}
        if(liveSummaryDraftTimer==null) {
            liveSummaryDraftTimer=new javax.swing.Timer(100,event->{
                if(liveGenerationKey!=null&&!closed)refreshStreamingSummaryPanes();
            });
            liveSummaryDraftTimer.setRepeats(false);
        }
        if(!liveSummaryDraftTimer.isRunning())liveSummaryDraftTimer.start();
    }

    private void refreshStreamingSummaryPanes() {
        if(deferSummaryRender())return;
        if(LayoutMotionPanel.defer(summaryScroll,"summary-stream",this::refreshStreamingSummaryPanes))return;
        if(liveSummaryDraftStructureDirty || !liveSummaryDraftPanes.keySet().containsAll(liveSummaryDrafts.keySet())) {
            renderSummary(true);liveSummaryDraftStructureDirty=false;return;
        }
        int oldY=summaryScroll.getViewport().getViewPosition().y;
        int previousMax=summaryScroll.getViewport().getViewSize().height-summaryScroll.getViewport().getExtentSize().height;
        boolean followEnd=oldY>=Math.max(0,previousMax-3);
        long interaction=summaryScrollInteraction;
        OutlineAnchor anchor=followEnd?null:captureSummaryOutlineAnchor();
        liveSummaryDrafts.forEach((number,draft)->streamingSummaryPane(number,draft,summaryFontSize.getValue()));
        if(liveOverviewStreaming && liveOverview!=null && liveOverviewStreamPane!=null)streamingOverviewPane(summaryFontSize.getValue());
        summaryFlow.revalidate();
        restoreSummaryScroll(oldY,followEnd,interaction,anchor);
        startLiveSummaryMotion();
    }

    private void startLiveSummaryTimer() {
        if(liveSummaryTimer==null)liveSummaryTimer=new javax.swing.Timer(65,event->advanceLiveSummary());
        if(!liveSummaryTimer.isRunning())liveSummaryTimer.start();
    }
    private void refreshLiveSummaryPreview() {
        if(deferSummaryRender()&&deferStudyView(conceptOverview)) {conceptRenderPending=true;return;}
        if(LayoutMotionPanel.defer(summaryScroll,"summary-preview",this::refreshLiveSummaryPreview))return;
        // Show the first result immediately. Parallel completions arriving in a
        // burst share the next frame instead of laying out all rich prose N times.
        if(liveSummarySections.size()==1) {renderSummary(true);showConcepts(true);return;}
        if(liveSummaryRefreshTimer==null) {
            liveSummaryRefreshTimer=new javax.swing.Timer(100,event->{
                if(liveGenerationKey!=null && !closed){renderSummary(true);showConcepts(true);}
            });
            liveSummaryRefreshTimer.setRepeats(false);
        }
        if(!liveSummaryRefreshTimer.isRunning())liveSummaryRefreshTimer.start();
    }
    private void advanceLiveSummary() {
        if(deferSummaryRender()) {
            // Keep canonical results, but do not replay typing on a hidden tab.
            liveSummarySections.forEach((number,section)->{
                String body=str(section,"body");liveSummaryVisible.put(number,body.codePointCount(0,body.length()));
            });
            liveSummaryFades.clear();
            liveSummarySpaces.values().forEach(SummaryStreamSpace::settle);
            liveStreamPanes().forEach(p->{SummaryStreamText text=SummaryStreamText.of(p);if(text!=null)text.finish();});
            if(liveSummaryTimer!=null)liveSummaryTimer.stop();
            completeLiveSummaryIfReady();return;
        }
        if(LayoutMotionPanel.defer(summaryScroll,"summary-typing",()->{
            if(!closed&&liveGenerationKey!=null){advanceLiveSummary();startLiveSummaryTimer();}
        })) {if(liveSummaryTimer!=null)liveSummaryTimer.stop();return;}
        boolean advanced=false;
        for(Map.Entry<Integer,JsonObject> entry:liveSummarySections.entrySet()) {
            String content=str(entry.getValue(),"body");
            int length=content.codePointCount(0,content.length());
            int visible=liveSummaryVisible.getOrDefault(entry.getKey(),0);
            if(visible<length) {
                int next=Math.min(length,visible+Math.max(24,(length+14)/15));
                liveSummaryVisible.put(entry.getKey(),next);
                TutorStreamFade fade=liveSummaryFades.get(entry.getKey());
                if(fade!=null) {
                    String shown=content.substring(0,content.offsetByCodePoints(0,next));
                    fade.accept("<p>"+escape(shown)+"</p>",System.currentTimeMillis());
                }
                advanced=true;
            }
        }
        if(advanced) {
            renderSummary(true);
            return;
        }
        if(liveSummaryFades.values().stream().anyMatch(fade->fade.active(System.currentTimeMillis()))) {
            renderSummary(true);
            return;
        }
        liveSummaryTimer.stop();
        completeLiveSummaryIfReady();
    }
    private boolean liveSummaryTyping() {
        for(Map.Entry<Integer,JsonObject> entry:liveSummarySections.entrySet()) {
            String body=str(entry.getValue(),"body");
            if(liveSummaryVisible.getOrDefault(entry.getKey(),0)<body.codePointCount(0,body.length()))return true;
        }
        return liveSummaryFades.values().stream().anyMatch(fade->fade.active(System.currentTimeMillis()))
            ||liveSummarySpaces.values().stream().anyMatch(SummaryStreamSpace::moving)
            ||liveStreamPanes().stream().anyMatch(p->SummaryStreamText.of(p)!=null&&SummaryStreamText.of(p).active(System.nanoTime()));
    }

    private String renderWithSlideLens(String markdown,String key,SlideLens.Request request,
                                       Map<String,SlideLens.Request> modules,boolean[] placed,int fontSize) {
        Matcher marker=SLIDE_LENS_INLINE.matcher(markdown);
        StringBuilder rendered=new StringBuilder();int start=0;
        while(marker.find()) {
            rendered.append(StudyMarkdown.renderWithScrollableMath(markdown.substring(start,marker.start()),fontSize));
            if(request!=null && !placed[0]) {
                modules.put(key,request);
                rendered.append("<!--SLIDELENS:").append(key).append("-->");
                placed[0]=true;
            }
            start=marker.end();
        }
        rendered.append(StudyMarkdown.renderWithScrollableMath(markdown.substring(start),fontSize));
        return rendered.toString().replace("[[SLIDE_LENS]]", "");
    }

    private void appendSlideLensMarker(StringBuilder html,JsonObject block,String key,
                                       Map<String,SlideLens.Request> modules,boolean placed) {
        StepFlow.Model sequence=StepFlow.resolve(block,index);
        if(sequence!=null) {
            String sequenceKey=key+"/step-flow";
            summaryStepFlows.put(sequenceKey,sequence);
            html.append("<!--SLIDELENS:").append(sequenceKey).append("-->");
        } else html.append(StepFlow.fallbackHtml(block,index,summaryFontSize.getValue()));
        SlideLens.Request request=validatedSlideLens(block);
        if(request!=null && !placed) {
            modules.put(key,request);
            html.append("<!--SLIDELENS:").append(key).append("-->");
        }
    }

    private static boolean moduleHasEvidence(JsonObject block,int page) {
        if(block.has("evidence") && block.get("evidence").isJsonArray())
            for(JsonElement item:block.getAsJsonArray("evidence"))
                try {if(item.getAsJsonObject().get("page").getAsInt()==page)return true;}
                catch(RuntimeException ignored) {}
        if(block.has("visualPages") && block.get("visualPages").isJsonArray())
            for(JsonElement item:block.getAsJsonArray("visualPages"))
                try {if(item.getAsInt()==page)return true;}
                catch(RuntimeException ignored) {}
        return false;
    }

    private void renderSummaryContent(String body,Map<String,SlideLens.Request> modules) {
        summaryOutlineTargets=Map.of();summaryOutlineOffsets.clear();
        int fontSize=summaryFontSize.getValue();
        SummarySkin.FormulaPresentation presentation=summaryReadingSkin?SummarySkin.prepare(body):null;
        if(presentation!=null)body=presentation.body();
        Set<String> usedGroups=new HashSet<>();
        Set<String> usedMath=new HashSet<>();
        Map<String,Integer> mathOccurrences=new HashMap<>();
        if(modules.isEmpty() && summaryStepFlows.isEmpty() && !body.contains("<!--MATHSCROLL:") && !body.contains("<!--READINGBREAK-->") && !body.contains("<!--FORMULAGROUP:") && !body.contains("<!--SUMMARYACTIVITY-->") && !body.contains("<!--OVERVIEWSTART-->") && !body.contains("<!--LIVEOVERVIEWSTART-->") && !body.contains("<!--SUMMARYSTREAM:") && !body.contains("<!--SUMMARYSPACE:")) {
            summary.setOpaque(true);
            setSummaryText(summary,"강의 해설",body,fontSize);
            StudySelectionContext.inherit((JComponent)summary,null);
            summaryProsePanes.clear();summaryMathPanes.clear();summaryFormulaGroups.clear();
            summaryFlow.removeAll();
            summaryFlow.add(summary);
            summarySelection.refresh();
            if(summaryScroll.getViewport().getView()!=summaryFlow)summaryScroll.setViewportView(summaryFlow);
            summaryFlow.pruneMeasurements();summaryFlow.revalidate();
            return;
        }
        summaryFlow.removeAll();
        Matcher marker=SUMMARY_CONTENT_MARKER.matcher(body);
        SummaryFlow target=summaryFlow;
        boolean progressOverview=false;
        int start=0, part=0;String origin=null;
        while(marker.find()) {
            String fragment=body.substring(start,marker.start());
            String moduleKey=marker.group(1);
            if(marker.group(9)!=null&&fragment.isBlank()) {
                SummaryStreamSpace space=liveSummarySpaces.get(Integer.parseInt(marker.group(9)));
                if(space!=null)target.add(space);start=marker.end();continue;
            }
            JEditorPane pane=summaryFragmentPane(part++);
            pane.setOpaque(target==summaryFlow);
            setSummaryText(pane,part==1?"강의 해설":"",fragment,fontSize);
            StudySelectionContext.inherit(pane,origin);origin=StudySelectionContext.lastOrigin(fragment,origin);
            target.add(pane);
            if(marker.group(9)!=null) {
                SummaryStreamSpace space=liveSummarySpaces.get(Integer.parseInt(marker.group(9)));
                if(space!=null)target.add(space);start=marker.end();continue;
            }
            if(marker.group(6)!=null) {
                progressOverview=marker.group(6).equals("LIVEOVERVIEWSTART");
                summaryOverviewContent.removeAll();summaryOverviewContent.setOpaque(false);
                target=summaryOverviewContent;summaryFlow.add(summaryOverviewLoading);
                start=marker.end();continue;
            }
            if(marker.group(8)!=null) {
                int number=Integer.parseInt(marker.group(8));
                JsonObject draft=liveSummaryDrafts.get(number);
                if(draft!=null)target.add(streamingSummaryPane(number,draft,fontSize));
                start=marker.end();continue;
            }
            if(marker.group(7)!=null) {
                if(progressOverview && liveOverviewStreaming && liveOverview!=null) {
                    summaryOverviewContent.removeAll();
                    summaryOverviewContent.add(streamingOverviewPane(fontSize));
                    StudySelectionContext.inherit((JComponent)liveOverviewStreamPane,origin);
                    if(!citations(liveOverview).isBlank()) {
                        if(liveOverviewEvidencePane==null) {
                            liveOverviewEvidencePane=new StudyHtmlPane(true);configureSummaryPane(liveOverviewEvidencePane);
                        }
                        setSummaryText(liveOverviewEvidencePane,"",citations(liveOverview),fontSize);
                        liveOverviewEvidencePane.setOpaque(false);summaryOverviewContent.add(liveOverviewEvidencePane);
                    }
                }
                summaryOverviewContent.pruneMeasurements();
                String heading=scope.getSelectedIndex()==0?"이 강의의 흐름":scope.getSelectedIndex()==1?"이 페이지의 핵심":"이 범위의 흐름";
                if(progressOverview)summaryOverviewLoading.showProgress(summaryOverviewContent,heading,fontSize,summaryActivity.state());
                else summaryOverviewLoading.complete(summaryOverviewContent,heading,fontSize);
                summaryFlow.add(Box.createVerticalStrut(10));
                target=summaryFlow;start=marker.end();continue;
            }
            if(marker.group(3)!=null) {start=marker.end();continue;}
            if(marker.group(5)!=null) {
                summaryOverviewLoading.clearProgressContent();
                summaryOverviewLoading.update(summaryActivity.state(),fontSize,hasLiveSummaryContent());
                summaryFlow.add(summaryOverviewLoading);start=marker.end();continue;
            }
            if(marker.group(4)!=null && presentation!=null) {
                SummarySkin.FormulaGroup content=presentation.groups().get(marker.group(4));
                int occurrence=mathOccurrences.merge("group/"+content,1,Integer::sum);
                String key=fontSize+"/"+occurrence+"/"+content;
                usedGroups.add(key);
                SummaryFormulaGroup group=summaryFormulaGroups.computeIfAbsent(key,
                    ignored->new SummaryFormulaGroup(content,fontSize,this::navigate,
                        SummarySkin.blackTextDocument(SummarySkin.formulaDocument(content.body(),fontSize)),null));
                StudySelectionContext.inherit(group,origin);target.add(group);
                start=marker.end();continue;
            }
            if(marker.group(2)!=null) {
                StudyMarkdown.ScrollableMath equation=StudyMarkdown.scrollableMath(marker.group(2));
                if(equation!=null) {
                    int occurrence=mathOccurrences.merge(marker.group(2),1,Integer::sum);
                    String cacheKey=marker.group(2)+"/"+occurrence+"/"+fontSize+"/"+summaryReadingSkin;
                    usedMath.add(cacheKey);
                    MathScrollPane equationPane=summaryMathPanes.computeIfAbsent(cacheKey,
                        ignored->new MathScrollPane(equation,fontSize,false,summaryReadingSkin,true));
                    StudySelectionContext.inherit(equationPane,origin);target.add(equationPane);
                }
                start=marker.end();
                continue;
            }
            SlideLens.Request request=modules.get(moduleKey);
            if(request!=null) target.add(slideLensPanel(request,moduleKey,()->preserveSummaryLensPosition(moduleKey,()->renderSummary(true))));
            StepFlow.Model sequence=summaryStepFlows.get(moduleKey);
            if(sequence!=null)target.add(stepFlowPanel(sequence,moduleKey,fontSize,true));
            start=marker.end();
        }
        if(start<body.length()) {
            JEditorPane pane=summaryFragmentPane(part++);
            pane.setOpaque(target==summaryFlow);
            setSummaryText(pane,"",body.substring(start),fontSize);
            StudySelectionContext.inherit(pane,origin);
            target.add(pane);
        }
        int count=part;
        summaryProsePanes.keySet().removeIf(number->number>=count);
        summaryMathPanes.keySet().retainAll(usedMath);
        summaryFormulaGroups.keySet().retainAll(usedGroups);
        summarySelection.refresh();
        if(summaryScroll.getViewport().getView()!=summaryFlow)summaryScroll.setViewportView(summaryFlow);
        summaryFlow.pruneMeasurements();summaryFlow.revalidate();
    }

    private JEditorPane summaryFragmentPane(int number) {
        if(number==0)return summary;
        return summaryProsePanes.computeIfAbsent(number,ignored->{
            JEditorPane pane=html(true);
            configureSummaryPane(pane);
            pane.addHyperlinkListener(e->{if(e.getEventType()==javax.swing.event.HyperlinkEvent.EventType.ACTIVATED)navigate(e.getDescription());});
            return pane;
        });
    }
    private void setSummaryText(JEditorPane pane,String title,String body,int fontSize) {
        String content=summaryDocumentHtml(title,body,fontSize);
        if(content.equals(pane.getClientProperty("synesis.summaryHtml"))
            && Objects.equals(pane.getClientProperty("synesis.summaryRevision"),((StudyHtmlPane)pane).contentRevision()))return;
        ((StudyHtmlPane)pane).setReadingSkin(summaryReadingSkin);
        pane.setText(content);
        pane.putClientProperty("synesis.summaryHtml",content);
        pane.putClientProperty("synesis.summaryRevision",((StudyHtmlPane)pane).contentRevision());
    }

    private StepFlow.Panel stepFlowPanel(StepFlow.Model model,String key,int fontSize) {
        return stepFlowPanel(model,key,fontSize,false);
    }
    private StepFlow.Panel stepFlowPanel(StepFlow.Model model,String key,int fontSize,boolean blackText) {
        return new StepFlow.Panel(model,fontSize,selectedSteps.getOrDefault(key,0),
            selected->{selectedSteps.put(key,selected);summaryFlow.revalidate();conceptList.revalidate();},
            number->navigate("page:"+number),blackText);
    }

    private SlideLens.Panel slideLensPanel(SlideLens.Request request,String key,Runnable refresh) {
        PdfSource target=source;
        String imageKey=target.id+"/"+request.regionId();
        boolean open=expandedSlideLens.contains(key);
        BufferedImage image=slideLensImages.get(imageKey);
        if(open && image==null && !slideLensErrors.containsKey(imageKey) && pendingSlideLens.add(imageKey)) {
            try {renders.execute(()->{
                BufferedImage cropped=null;String error=null;
                try {cropped=SlideLens.crop(target,request);}
                catch(Exception failure) {error="영역을 가져오지 못했습니다. PDF 원본을 확인해 주세요.";}
                BufferedImage result=cropped;String message=error;
                SwingUtilities.invokeLater(()->{
                    pendingSlideLens.remove(imageKey);
                    if(closed || source!=target)return;
                    if(result!=null)slideLensImages.put(imageKey,result);
                    else slideLensErrors.put(imageKey,message);
                    if(!expandedSlideLens.contains(key))return;
                    Integer anchor=loadingSummaryLensAnchors.remove(key);
                    preserveSummaryLensPosition(key,()->renderSummary(true),anchor);showConcepts(true);
                });
            });}catch(RejectedExecutionException stopped){pendingSlideLens.remove(imageKey);}
        }
        SlideLens.Panel panel=new SlideLens.Panel(request,image,slideLensErrors.get(imageKey),open,
            slideLensWidths.getOrDefault(imageKey,480),
            ()->{
                if(!expandedSlideLens.add(key)) {
                    expandedSlideLens.remove(key);
                    loadingSummaryLensAnchors.remove(key);
                } else {
                    slideLensErrors.remove(imageKey);
                    if(image==null) {
                        SlideLens.Panel summaryPanel=summaryLensPanel(key);
                        if(summaryPanel!=null && summaryScroll.getViewport().getView()==summaryFlow)
                            loadingSummaryLensAnchors.put(key,SwingUtilities.convertPoint(summaryPanel,0,0,summaryScroll.getViewport()).y);
                    }
                }
                refresh.run();
            },
            width->{slideLensWidths.put(imageKey,width);summaryFlow.revalidate();conceptList.revalidate();});
        panel.setName(key);
        return panel;
    }

    private void preserveSummaryLensPosition(String key,Runnable refresh) {
        preserveSummaryLensPosition(key,refresh,null);
    }

    private void preserveSummaryLensPosition(String key,Runnable refresh,Integer requestedY) {
        SlideLens.Panel before=summaryLensPanel(key);
        JViewport viewport=summaryScroll.getViewport();
        if(before==null || viewport.getView()!=summaryFlow) {refresh.run();return;}
        int viewportY=requestedY!=null?requestedY:SwingUtilities.convertPoint(before,0,0,viewport).y;
        refresh.run();
        SwingUtilities.invokeLater(()->{
            if(closed || viewport.getView()!=summaryFlow)return;
            SlideLens.Panel after=summaryLensPanel(key);
            if(after==null)return;
            summaryScroll.validate();
            summaryFlow.doLayout();
            summaryScroll.getVerticalScrollBar().setValue(after.getY()-viewportY);
        });
    }

    private SlideLens.Panel summaryLensPanel(String key) {
        for(Component child:summaryFlow.getComponents())
            if(child instanceof SlideLens.Panel panel && key.equals(panel.getName()))return panel;
        return null;
    }

    private static String visualCitations(JsonObject block) {
        // Visual provenance remains in the saved result; it is not a student action.
        return "";
    }
    private static String studentText(JsonObject block,String key) {
        String value=str(block,key);
        JsonArray evidence=block.has("evidence") && block.get("evidence").isJsonArray()?block.getAsJsonArray("evidence"):null;
        if(evidence==null || evidence.isEmpty()) return value;
        for(JsonElement item:evidence) if(!"native".equals(str(item.getAsJsonObject(),"source"))) return value;
        // Older generated results sometimes mislabel damaged embedded-font text as image OCR.
        return value.replaceAll("\\s*\\[OCR 표기 불확실:[^\\]]*\\]", "");
    }

    private static final class MathScrollPane extends SmoothScrollPane {
        private final boolean readingSkin;
        MathScrollPane(StudyMarkdown.ScrollableMath equation,int fontSize) {
            this(equation,fontSize,false);
        }
        MathScrollPane(StudyMarkdown.ScrollableMath equation,int fontSize,boolean dark) {
            this(equation,fontSize,dark,false);
        }
        MathScrollPane(StudyMarkdown.ScrollableMath equation,int fontSize,boolean dark,boolean readingSkin) {
            this(equation,fontSize,dark,readingSkin,false);
        }
        MathScrollPane(StudyMarkdown.ScrollableMath equation,int fontSize,boolean dark,boolean readingSkin,boolean blackText) {
            super(new StudyHtmlPane());
            this.readingSkin=readingSkin;
            StudyHtmlPane text=(StudyHtmlPane)getViewport().getView();
            if(dark)useTutorFont(text);
            text.setEditable(false);
            Color background=dark?TUTOR_ASSISTANT_FILL:Color.WHITE;
            text.setBackground(background);
            text.setBorder(BorderFactory.createEmptyBorder());
            text.putClientProperty(JEditorPane.HONOR_DISPLAY_PROPERTIES,true);
            text.setFont(new Font(UiFonts.FAMILY,Font.PLAIN,fontSize));
            String document=dark?tutorDocumentHtml(equation.html(),fontSize):
                "<html><head><style>body{margin:3px 6px;font-size:"+fontSize
                +"pt;white-space:nowrap;"+(readingSkin?"text-align:center;":"")+"}</style></head><body>"+equation.html()+"</body></html>";
            text.setText(blackText?SummarySkin.blackTextDocument(document):document);
            text.setSize(equation.width(),equation.height());
            javax.swing.text.View root=text.getUI().getRootView(text);
            int naturalWidth=Math.max(equation.width(),(int)Math.ceil(root.getMinimumSpan(javax.swing.text.View.X_AXIS))+16);
            text.setSize(naturalWidth,Short.MAX_VALUE);
            try {text.modelToView2D(text.getDocument().getLength());}
            catch(javax.swing.text.BadLocationException ignored) { /* Use the view's measured span. */ }
            int naturalHeight=Math.max(equation.height(),(int)Math.ceil(root.getPreferredSpan(javax.swing.text.View.Y_AXIS))+8);
            text.setPreferredSize(new Dimension(naturalWidth,naturalHeight));
            setBorder(BorderFactory.createEmptyBorder(4,0,8,0));
            if(readingSkin) {setBorder(BorderFactory.createEmptyBorder(4,0,8,0));setOpaque(false);}
            setBackground(background);getViewport().setBackground(background);
            setHorizontalScrollBarPolicy(HORIZONTAL_SCROLLBAR_AS_NEEDED);
            setVerticalScrollBarPolicy(VERTICAL_SCROLLBAR_NEVER);
            getHorizontalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
            if(dark)styleTutorScrollBars(this);
            setPreferredSize(new Dimension(640,naturalHeight+getHorizontalScrollBar().getPreferredSize().height+12));
            setMaximumSize(new Dimension(Integer.MAX_VALUE,getPreferredSize().height));
            setAlignmentX(Component.LEFT_ALIGNMENT);
        }
        @Override protected void processMouseWheelEvent(MouseWheelEvent event) {
            if(event.isShiftDown()) {
                super.processMouseWheelEvent(event);
                return;
            }
            JScrollPane outer=(JScrollPane)SwingUtilities.getAncestorOfClass(JScrollPane.class,this);
            if(outer==null) {super.processMouseWheelEvent(event);return;}
            Point point=SwingUtilities.convertPoint(this,event.getPoint(),outer);
            outer.dispatchEvent(new MouseWheelEvent(outer,event.getID(),event.getWhen(),event.getModifiersEx(),
                point.x,point.y,event.getXOnScreen(),event.getYOnScreen(),event.getClickCount(),
                event.isPopupTrigger(),event.getScrollType(),event.getScrollAmount(),
                event.getWheelRotation(),event.getPreciseWheelRotation()));
            event.consume();
        }
    }

    static boolean isEmptyStudyPlaceholder(JsonObject section) {
        if(section==null)return false;
        if(section.has("studyContentSkipped") && section.get("studyContentSkipped").getAsBoolean())return true;
        return "학습 내용 없음".equals(str(section,"title"))
            && (!section.has("evidence") || section.getAsJsonArray("evidence").isEmpty())
            && (!section.has("visualPages") || section.getAsJsonArray("visualPages").isEmpty());
    }
    private String summaryBlock(JsonObject block,String key,boolean showTitle,
                                Map<String,SlideLens.Request> modules) {
        StringBuilder html=new StringBuilder(selectionOrigin(summarySelectionSources,block,key,str(block,"title")));
        if(!key.endsWith("/overview"))html.append("<a name='synesis-summary-content'></a>");
        if(showTitle) {
            html.append("<h3>").append(escape(str(block,"title")))
                .append(headingCitations(block)).append("</h3>");
        }
        JsonArray parts=block.has("parts") && block.get("parts").isJsonArray()?block.getAsJsonArray("parts"):null;
        boolean hasPartEasy=false;
        if(parts!=null && !parts.isEmpty()) {
            String parentTitle=showTitle?str(block,"title").strip().replaceAll("\\s+"," "):"";
            int headingCount=0;
            for(JsonElement item:parts) {
                String title=str(item.getAsJsonObject(),"title").strip();
                if(!title.isEmpty() && !title.replaceAll("\\s+"," ").equals(parentTitle))headingCount++;
            }
            int partNumber=0,headingNumber=0;
            for(JsonElement item:parts) {
                JsonObject part=item.getAsJsonObject();
                String partKey=key+"/part-"+(partNumber++);
                String partTitle=str(part,"title").strip();
                if(!partTitle.isEmpty() && !partTitle.replaceAll("\\s+"," ").equals(parentTitle)) {
                    html.append("<h4>");
                    if(headingCount>1)html.append(++headingNumber).append(". ");
                    html.append(escape(partTitle)).append(headingCitations(part)).append("</h4>");
                }
                boolean[] placed={false};
                html.append(selectionOrigin(summarySelectionSources,part,partKey,partTitle.isEmpty()?str(block,"title"):partTitle));
                html.append(renderWithSlideLens(studentText(part,"body"),partKey,validatedSlideLens(part),
                        modules,placed,summaryFontSize.getValue()))
                    .append(citations(part));
                appendSlideLensMarker(html,part,partKey,modules,placed[0]);
                html.append(summaryEasyBlock(part,partKey));
                hasPartEasy |= !studentText(part,"easyExplanation").isBlank();
            }
        } else {
            boolean[] placed={false};
            html.append(renderWithSlideLens(studentText(block,"body"),key,validatedSlideLens(block),
                    modules,placed,summaryFontSize.getValue()))
                .append(citations(block));
            appendSlideLensMarker(html,block,key,modules,placed[0]);
        }
        html.append(visualCitations(block));
        // Legacy results only have a section-level explanation. Keep it available until regeneration.
        if(!hasPartEasy) html.append(summaryEasyBlock(block,key));
        return html.toString();
    }

    private String summaryHierarchy(List<SummaryOutline.Entry> entries,String prefix,Map<String,SlideLens.Request> modules) {
        StringBuilder out=new StringBuilder("<a name='synesis-summary-content'></a>");
        boolean followsHeadingOnlyParent=false;
        for(int entryIndex=0;entryIndex<entries.size();entryIndex++) {
            SummaryOutline.Entry entry=entries.get(entryIndex);
            boolean headingOnlyParent=entry.content().isEmpty()&&entryIndex+1<entries.size()
                &&entries.get(entryIndex+1).parentId().equals(entry.id());
            // A structural parent has no missing paragraph: keep its child in
            // the same reading fragment with a small gap, rather than stacking
            // independent section margins and fragment padding between titles.
            if(summaryReadingSkin&&entry.level()<=2&&!followsHeadingOnlyParent)out.append("<!--READINGBREAK-->");
            out.append(SummaryOutline.heading(entry,followsHeadingOnlyParent,headingOnlyParent));int index=0;
            for(JsonObject content:entry.content()) {
                String id=content.has("contentId")?str(content,"contentId"):entry.id()+"/"+(index++);
                if(content.has("_liveSummaryUnit"))out.append("<!--SUMMARYSTREAM:")
                    .append(content.get("_liveSummaryUnit").getAsInt()).append("--><!--SUMMARYSPACE:")
                    .append(content.get("_liveSummaryUnit").getAsInt()).append("-->");
                else out.append(summaryBlock(content,prefix+"/"+id,false,modules));
                if(content.has("_liveSummarySpace"))out.append("<!--SUMMARYSPACE:")
                    .append(content.get("_liveSummarySpace").getAsInt()).append("-->");
            }
            // Separate completed title/body groups at their end; heading-only parents
            // stay attached to their first child and keep the compact heading spacing.
            if(!entry.content().isEmpty() && entryIndex+1<entries.size())
                out.append("<div style='margin:0 0 24px 0;font-size:1pt;'>&#8203;</div>");
            followsHeadingOnlyParent=headingOnlyParent;
        }
        return out.toString();
    }

    private void configureSummaryOutline() {
        summaryOutlineTree.addMouseListener(new java.awt.event.MouseAdapter(){
            @Override public void mouseClicked(java.awt.event.MouseEvent e){
                if(!SwingUtilities.isLeftMouseButton(e))return;
                var path=summaryOutlineTree.getPathForLocation(e.getX(),e.getY());
                if(path!=null)activateSummaryOutline(path);
            }
        });
        summaryOutlineTree.getInputMap().put(KeyStroke.getKeyStroke("ENTER"),"outline-jump");
        summaryOutlineTree.getActionMap().put("outline-jump",new AbstractAction(){
            @Override public void actionPerformed(java.awt.event.ActionEvent e){activateSummaryOutline(summaryOutlineTree.getSelectionPath());}
        });
        JScrollPane scroll=new SmoothScrollPane(summaryOutlineTree);scroll.setBorder(null);
        scroll.setPreferredSize(new Dimension(300,360));summaryOutlinePopup.add(scroll);
        summaryOutlinePopup.setInvoker(summaryOutlineButton);
        scroll.getVerticalScrollBar().setUI(new dev.synesis.poc.ui.FadingScrollBarUI(Color.BLACK,.2f));
        scroll.getHorizontalScrollBar().setUI(new dev.synesis.poc.ui.FadingScrollBarUI(Color.BLACK,.2f));
        scroll.setBackground(Color.WHITE);scroll.getViewport().setBackground(Color.WHITE);
        summaryOutlineHover.trackPopup(summaryOutlinePopup);
    }

    private void refreshSummaryOutlineTree() {
        summaryOutlineButton.setEnabled(!summaryOutlineEntries.isEmpty());
        if(!summaryOutlinePopup.isVisible()&&summaryOutlineEntries.isEmpty())return;
        var root=new javax.swing.tree.DefaultMutableTreeNode("목차");
        Map<String,javax.swing.tree.DefaultMutableTreeNode> nodes=new HashMap<>();summaryOutlinePaths.clear();
        for(SummaryOutline.Entry entry:summaryOutlineEntries) {
            var node=new javax.swing.tree.DefaultMutableTreeNode(entry);nodes.put(entry.id(),node);
            nodes.getOrDefault(entry.parentId(),root).add(node);
            summaryOutlinePaths.put(entry.id(),new javax.swing.tree.TreePath(node.getPath()));
        }
        summaryOutlineTree.setModel(new javax.swing.tree.DefaultTreeModel(root));
        for(SummaryOutline.Entry entry:summaryOutlineEntries)if(entry.level()<4)
            summaryOutlineTree.expandPath(summaryOutlinePaths.get(entry.id()));
        updateSummaryOutlineSelection();
    }

    private void activateSummaryOutline(javax.swing.tree.TreePath path) {
        if(path==null)return;
        Object value=((javax.swing.tree.DefaultMutableTreeNode)path.getLastPathComponent()).getUserObject();
        if(!(value instanceof SummaryOutline.Entry entry))return;
        scrollSummaryEntry(entry);
    }

    private void scrollSummaryEntry(SummaryOutline.Entry entry) {
        summaryOutlineTargets=SummaryOutline.targets(summaryFlow);
        Integer y=summaryOutlineY(summaryOutlineTargets.get(entry.id()));if(y==null)return;
        summaryScrollInteraction++;
        int max=Math.max(0,summaryFlow.getHeight()-summaryScroll.getViewport().getHeight());
        summaryScroll.getViewport().setViewPosition(new Point(0,Math.max(0,Math.min(y,max))));
        summaryOutlinePopup.setVisible(false);
    }

    private Integer summaryOutlineY(SummaryOutline.Target target) {
        if(target==null)return null;
        try {
            var box=target.pane().modelToView2D(target.offset());
            return box==null?null:SwingUtilities.convertRectangle(target.pane(),box.getBounds(),summaryFlow).y;
        }catch(javax.swing.text.BadLocationException ignored){return null;}
    }

    private OutlineAnchor captureSummaryOutlineAnchor() {
        if(summaryOutlineEntries.isEmpty())return null;
        int y=summaryScroll.getViewport().getViewPosition().y;OutlineAnchor found=null;int nearest=-1;
        for(var item:summaryTargets().entrySet()) {
            Integer at=summaryOutlineY(item.getValue());
            if(at!=null&&at<=y&&at>=nearest){nearest=at;found=new OutlineAnchor(item.getKey(),y-at);}
        }
        return found;
    }
    private Map<String,SummaryOutline.Target> summaryTargets() {
        if(summaryOutlineTargets.isEmpty())summaryOutlineTargets=SummaryOutline.targets(summaryFlow);
        return summaryOutlineTargets;
    }

    private void updateSummaryOutlineSelection() {
        if(!summaryOutlinePopup.isVisible())return;
        if(summaryOutlineOffsets.isEmpty()) {
            summaryOutlineTargets=SummaryOutline.targets(summaryFlow);
            for(var item:summaryOutlineTargets.entrySet()) {
                Integer at=summaryOutlineY(item.getValue());if(at!=null)summaryOutlineOffsets.put(at,item.getKey());
            }
        }
        var current=summaryOutlineOffsets.floorEntry(summaryScroll.getViewport().getViewPosition().y
            +summaryScroll.getViewport().getExtentSize().height/2);
        if(current==null)current=summaryOutlineOffsets.firstEntry();
        if(current==null)return;
        var path=summaryOutlinePaths.get(current.getValue());
        summaryOutlineTree.current(current.getValue());
        if(path!=null&&!path.equals(summaryOutlineTree.getSelectionPath())) {
            summaryOutlineTree.setSelectionPath(path);summaryOutlineTree.scrollPathToVisible(path);
        }
    }
    /** Width-aware stack so HTML fragments wrap around native study modules. */
    private static final class SummaryFlow extends JPanel implements Scrollable {
        private static final int MAX_READING_WIDTH = 800;
        private final int bottomPadding;
        private record Measurement(int width,long revision,Font font,int height) {}
        private final Map<Component,Measurement> measurements=new IdentityHashMap<>();
        void pruneMeasurements() {measurements.keySet().removeIf(child->child.getParent()!=this);}
        SummaryFlow() { this(0); }
        SummaryFlow(int bottomPadding) {
            super(null);
            this.bottomPadding=bottomPadding;
            setBackground(Color.WHITE);
            addMouseListener(new java.awt.event.MouseAdapter() {
                @Override public void mouseClicked(java.awt.event.MouseEvent event) {
                    if(getClientProperty(StudySelectionActions.class)!=null)return;
                    if(!SwingUtilities.isLeftMouseButton(event) || event.getClickCount()!=1)return;
                    clearSelections(SummaryFlow.this);
                }
            });
        }
        private static void clearSelections(Container container) {
            for(Component child:container.getComponents()) {
                if(child instanceof StudyHtmlPane pane && pane.getSelectionStart()!=pane.getSelectionEnd())
                    pane.clearSelectionAt(pane.getCaretPosition());
                else if(child instanceof Container nested)clearSelections(nested);
            }
        }
        private int contentWidth() {
            return Math.max(1, getParent() instanceof JViewport viewport ? viewport.getWidth() : getWidth());
        }
        private int childWidth(Component child,int width) {
            // Share the reading column across prose and native study modules so
            // excess viewport width becomes equal left and right margins.
            int column=Math.min(width,MAX_READING_WIDTH);
            // Match the HTML reading inset for native wide-equation cards as well.
            if(child instanceof MathScrollPane equation && equation.readingSkin || child instanceof SummaryFormulaGroup
                || child instanceof SummaryActivityBar)
                return Math.max(1,column-64);
            return column;
        }
        private int heightOf(Component child, int width) {
            int targetWidth=childWidth(child,width);
            StudyHtmlPane prose=child instanceof StudyHtmlPane pane?pane:null;
            Measurement cached=measurements.get(child);
            if(prose!=null && cached!=null && cached.width()==targetWidth
                && cached.revision()==prose.contentRevision() && Objects.equals(cached.font(),child.getFont()))
                return cached.height();
            if(prose!=null) {
                if(SummaryStreamText.of(prose)==null)child.setSize(targetWidth,Short.MAX_VALUE);
                else if(child.getWidth()!=targetWidth)child.setSize(targetWidth,Math.max(1,child.getHeight()));
                try {prose.modelToView2D(prose.getDocument().getLength());}
                catch(javax.swing.text.BadLocationException ignored) {}
            } else if(child.getWidth()!=targetWidth)child.setSize(targetWidth,Math.max(1,child.getHeight()));
            int height=Math.max(1, child.getPreferredSize().height);
            if(prose!=null&&prose.getClientProperty("synesis.summaryStreamSpace")instanceof SummaryStreamSpace space)space.measured(height,targetWidth);
            if(prose!=null)measurements.put(child,new Measurement(targetWidth,prose.contentRevision(),child.getFont(),height));
            return height;
        }
        @Override public Dimension getPreferredSize() {
            int width = contentWidth(), height = 0;
            for (Component child : getComponents()) height += heightOf(child, width);
            return new Dimension(width, Math.max(1, height+bottomPadding));
        }
        @Override public void doLayout() {
            int width = contentWidth(), y = 0;
            for (Component child : getComponents()) {
                int height = heightOf(child, width);
                int childWidth=childWidth(child,width);
                child.setBounds((width-childWidth)/2, y, childWidth, height);
                y += height;
            }
        }
        @Override public Dimension getPreferredScrollableViewportSize() { return new Dimension(500,500); }
        @Override public int getScrollableUnitIncrement(Rectangle visible,int orientation,int direction) { return 8; }
        @Override public int getScrollableBlockIncrement(Rectangle visible,int orientation,int direction) { return Math.max(24,visible.height-40); }
        @Override public boolean getScrollableTracksViewportWidth() { return true; }
        @Override public boolean getScrollableTracksViewportHeight() { return false; }
    }

    private String summaryEasyBlock(JsonObject block,String key) {
        StringBuilder html=new StringBuilder();
        String easy=studentText(block,"easyExplanation").strip();
        if(!easy.isEmpty()) {
            boolean open=expandedEasySummaries.contains(key);
            if(summaryReadingSkin) {
                html.append("<div class='study-easy'>").append(SummarySkin.easyHeader(key,open));
                if(open)html.append("<div class='study-easy-body'>").append(selectionOrigin(summarySelectionSources,block,key+"/easy",str(block,"title")))
                    .append(StudyMarkdown.renderWithScrollableMath(easy,summaryFontSize.getValue()))
                    .append(citations(block)).append(visualCitations(block)).append("</div>");
                return html.append("</div>").toString();
            }
            html.append("<table width='100%' cellpadding='9' cellspacing='0' bgcolor='#f4e9ed'><tr><td><a href='easy:")
                .append(escape(key)).append("'>쉬운 설명 ").append(open?"접기":"보기").append("</a></td></tr>");
            if(open) html.append("<tr><td bgcolor='#fafaf8'>").append(StudyMarkdown.render(easy,summaryFontSize.getValue()))
                .append(citations(block)).append(visualCitations(block)).append("</td></tr>");
            html.append("</table>");
        }
        return html.toString();
    }

    private Set<Integer> resultVisualPages(JsonObject result) {
        Set<Integer> pages=new TreeSet<>();
        if(result.has("visualNotePages")) for(JsonElement item:result.getAsJsonArray("visualNotePages")) pages.add(item.getAsInt());
        return pages;
    }
    private Set<Integer> currentVisualPages() {
        Set<Integer> pages=new TreeSet<>();
        if(source==null || index==null) return pages;
        int first=scope.getSelectedIndex()==0?1:scope.getSelectedIndex()==1?page:(page-1)/5*5+1;
        int last=scope.getSelectedIndex()==0?source.count:scope.getSelectedIndex()==1?page:Math.min(source.count,first+4);
        for(int number=first;number<=last;number++) {
            JsonObject p=index.getAsJsonArray("pages").get(number-1).getAsJsonObject();
            if(p.has("pageAnalysis")) {
                for(JsonElement item:p.getAsJsonObject("pageAnalysis").getAsJsonArray("elements")) {
                    JsonObject e=item.getAsJsonObject();
                    if(!"decoration".equals(str(e,"kind")) && (!str(e,"description").isBlank() || !e.getAsJsonArray("relationships").isEmpty()))pages.add(number);
                }
            } else if(!index.has("pageAnalysisVersion") && visualResult(source,number)!=null)pages.add(number);
        }
        return pages;
    }

    private String summaryStrategyId(){return STRATEGY_IDS[summaryStrategy.getSelectedIndex()];}
    private static boolean isRegionStrategy(String id){
        return PdfStudyStrategy.selectable(id)
            || Set.of("region-v1","region-local-v1","slide-v1","new-concept-v1","new-concept-v02").contains(id);
    }
    static boolean readableStudyVersion(String version) {
        return version.startsWith("pdf-grounded-ko-") || version.startsWith("semantic-")
            || version.equals("region-study-v1") || version.equals("new-concept-study-v1")
            || version.equals("new-concept-study-v2") || version.startsWith("new-concept-study-ver.02")
            || version.equals(PdfStudyStrategy.K1_2_5_PROMPT)
            || version.equals(PdfStudyStrategy.VER02_PROMPT) || version.equals(PdfStudyStrategy.VER99_PROMPT) || version.equals("Newest_m1-v1") || version.equals(PdfStudyStrategy.K1_PROMPT) || version.equals(PdfStudyStrategy.K11_PROMPT) || (version.equals(PdfStudyStrategy.K111_PROMPT) || (version.equals(PdfStudyStrategy.K1_1_1_PROMPT) || (version.equals(PdfStudyStrategy.K1_1_2_PROMPT) || (version.equals(PdfStudyStrategy.K1_1_3_PROMPT) || (version.equals(PdfStudyStrategy.K1_2_0_PROMPT) || (version.equals(PdfStudyStrategy.K1_2_1_PROMPT) || (version.equals(PdfStudyStrategy.K1_2_2_PROMPT) || version.equals(PdfStudyStrategy.K1_2_3_PROMPT))))))));
    }
    private String expectedStudyVersion() {
        return switch(summaryStrategyId()) {
            case "new-concept-v02" -> PdfStudyStrategy.VER02_PROMPT;
            case "new-concept-v99" -> PdfStudyStrategy.VER99_PROMPT;
            case "newest-m1" -> "Newest_m1-v1";
            case "newest-k1" -> PdfStudyStrategy.K1_PROMPT;
            case "newest-k1-1" -> PdfStudyStrategy.K11_PROMPT;
            case "newest-k1-11" -> PdfStudyStrategy.K111_PROMPT;
            case "newest-k1-1-1" -> PdfStudyStrategy.K1_1_1_PROMPT;
            case "newest-k1-1-2" -> PdfStudyStrategy.K1_1_2_PROMPT;
            case "newest-k1-1-3" -> PdfStudyStrategy.K1_1_3_PROMPT;
            case "newest-k1-2-0" -> PdfStudyStrategy.K1_2_0_PROMPT;
            case "newest-k1-2-1" -> PdfStudyStrategy.K1_2_1_PROMPT;
            case "newest-k1-2-2" -> PdfStudyStrategy.K1_2_2_PROMPT;
            case "newest-k1-2-3" -> PdfStudyStrategy.K1_2_3_PROMPT;
            case "newest-k1-2-4" -> PdfStudyStrategy.K1_2_4_PROMPT;
            case "newest-k1-2-5" -> PdfStudyStrategy.K1_2_5_PROMPT;
            case "new-concept-v1" -> "new-concept-study-v2";
            default -> isRegionStrategy(summaryStrategyId())?"region-study-v1":summaryStrategyId().equals(SEMANTIC_VERSION)?SEMANTIC_VERSION:GENERATION_PROMPT_VERSION;
        };
    }
    private static String strategyLabel(String id){for(int i=0;i<STRATEGY_IDS.length;i++)if(STRATEGY_IDS[i].equals(id))return STRATEGY_LABELS[i];return id;}
    private static String strategyFolder(String id){return id.equals(SEMANTIC_VERSION)?"generated/semantic":isRegionStrategy(id)?"generated/"+id:"generated";}
    private static List<Path> strategyFolders(Path folder){return Arrays.stream(STRATEGY_IDS).map(id->folder.resolve(strategyFolder(id))).toList();}
    /** Read and parse saved prose before handing it to Swing, never while painting/input waits. */
    static Map<String,JsonObject> loadSavedProducts(Path folder,String documentId,JsonObject document) {
        Map<String,JsonObject> saved=new LinkedHashMap<>();
        for(Path cacheFolder:strategyFolders(folder)) {
            if(Files.isDirectory(cacheFolder))try(var entries=Files.newDirectoryStream(cacheFolder,"latest-*.json")) {
                for(Path cached:entries)try {
                    byte[] latestBytes=Files.readAllBytes(cached);
                    JsonObject result=JsonParser.parseString(new String(latestBytes,StandardCharsets.UTF_8)).getAsJsonObject();
                    result=completedLocalProduct(cached,latestBytes,result);
                    if(documentId.equals(str(result,"documentId")) && compatibleFingerprint(result,document)
                            && readableStudyVersion(str(result,"promptVersion")))
                        saved.put(resultProductKey(result),result);
                }catch(Exception ignored) { /* A damaged or concurrently replaced cache does not hide other results. */ }
            }catch(IOException ignored) { /* Missing older strategies are expected on a new import. */ }
        }
        return saved;
    }
    /** Read an exact locally completed recovery without rewriting its partial latest or paid records. */
    private static JsonObject completedLocalProduct(Path latestPath,byte[] latestBytes,JsonObject latest) {
        if(!str(latest,"strategy").equals("new-concept-v99")||str(latest,"model").isBlank())return latest;
        try {
            Path parent=latestPath.getParent().toAbsolutePath().normalize();
            String scope=str(latest,"scope");int page=latest.get("page").getAsInt();
            if(!List.of("document","page","section").contains(scope))return latest;
            JsonObject pointer=readJson(parent.resolve("local-complete-"+scope+"-"+page+".json"));
            String rootName=str(pointer,"rootName");
            if(!rootName.matches("[0-9a-f]{64}"))return latest;
            java.security.MessageDigest hash=java.security.MessageDigest.getInstance("SHA-256");
            if(!java.util.HexFormat.of().formatHex(hash.digest(latestBytes)).equals(str(pointer,"originalLatestSha256")))return latest;
            Path resultPath=parent.resolve(rootName).resolve("result.json").toRealPath();
            if(!resultPath.startsWith(parent.toRealPath()))return latest;
            byte[] bytes=Files.readAllBytes(resultPath);
            if(!java.util.HexFormat.of().formatHex(hash.digest(bytes)).equals(str(pointer,"resultSha256")))return latest;
            JsonObject result=JsonParser.parseString(new String(bytes,StandardCharsets.UTF_8)).getAsJsonObject();
            for(String key:List.of("documentId","sourceFingerprint","strategy","model","scope","page"))
                if(!Objects.equals(result.get(key),latest.get(key)))return latest;
            JsonElement complete=result.get("processingComplete");
            if(complete==null||!complete.isJsonPrimitive()||!complete.getAsJsonPrimitive().isBoolean()||!complete.getAsBoolean())return latest;
            JsonObject recovery=result.getAsJsonObject("localRecovery");JsonElement calls=recovery.get("newPaidCalls");
            if(calls==null||!calls.isJsonPrimitive()||!calls.getAsJsonPrimitive().isNumber()
                    ||calls.getAsBigDecimal().compareTo(java.math.BigDecimal.ZERO)!=0)return latest;
            return result;
        } catch(Exception ignored) {return latest;}
    }

    static String strategyProductKey(String strategy,String scope,int page){return strategy+":"+scope+":"+(scope.equals("document")?0:scope.equals("section")?(page-1)/5*5+1:page);}
    private String productKey(String scope,int page){return strategyProductKey(summaryStrategyId(),scope,page);}
    private static String resultProductKey(JsonObject result){return strategyProductKey(
        Arrays.asList(STRATEGY_IDS).contains(str(result,"strategy"))?str(result,"strategy"):"page-v1",str(result,"scope"),result.get("page").getAsInt());}
    private void selectProduct(){
        String selected=switch(scope.getSelectedIndex()){case 1->"page";case 2->"section";default->"document";};
        String key=productKey(selected,page);generated=products.get(key);
        upgradeSavedHierarchy(key,generated);
    }

    private void upgradeSavedHierarchy(String key,JsonObject saved) {
        PdfSource target=source;JsonObject document=index;
        if(closed||target==null||document==null||!needsSavedHierarchyProjection(saved))return;
        int epoch=generation.get(),ticket=processes.ticket();
        HierarchyProjectionAttempt attempt=new HierarchyProjectionAttempt(target,document,epoch,ticket,saved);
        if(attempt.equals(hierarchyProjectionAttempts.get(key)))return;
        hierarchyProjectionAttempts.put(key,attempt);
        String strategy=str(saved,"strategy"),selectedScope=str(saved,"scope");
        int selectedPage=saved.get("page").getAsInt();String fingerprint=str(saved,"sourceFingerprint");
        try {jobs.execute(()->{
            if(closed||source!=target||index!=document||generation.get()!=epoch||processes.ticket()!=ticket)return;
            JsonObject recovered=savedHierarchyRecovery.recover(target,ticket,strategy,selectedScope,selectedPage,fingerprint);
            if(!validSavedHierarchyProjection(recovered,saved,document))return;
            SwingUtilities.invokeLater(()->{
                if(closed||source!=target||index!=document||generation.get()!=epoch||processes.ticket()!=ticket
                        ||products.get(key)!=saved)return;
                products.put(key,recovered);
                // Keep another scope's current selection and any arriving live
                // generation intact; the local projection remains cached here.
                if(generated==saved) {
                    generated=recovered;
                    if(!busy){renderSummary(true);showConcepts();setControls();}
                }
            });
        });}catch(RejectedExecutionException ignored) { /* A closing workspace keeps its saved result. */ }
    }

    static boolean needsSavedHierarchyProjection(JsonObject saved) {
        if(saved==null||!str(saved,"strategy").equals("new-concept-v99")||!saved.has("page")
                ||!List.of("document","page","section").contains(str(saved,"scope")))return false;
        JsonObject hierarchy=saved.has("hierarchy")&&saved.get("hierarchy").isJsonObject()?saved.getAsJsonObject("hierarchy"):null;
        return !str(hierarchy,"version").equals(LOCAL_HIERARCHY_VERSION)
            || !str(hierarchy,"displayRevision").equals(LOCAL_HIERARCHY_DISPLAY_REVISION);
    }

    

    

    

    

    static boolean validSavedHierarchyProjection(JsonObject recovered,JsonObject saved,JsonObject document) {
        try {
            return recovered!=null&&recoverableGeneration(recovered,str(saved,"documentId"),str(saved,"sourceFingerprint"))
                &&compatibleFingerprint(recovered,document)&&str(recovered,"strategy").equals(str(saved,"strategy"))
                &&resultProductKey(recovered).equals(resultProductKey(saved))&&!needsSavedHierarchyProjection(recovered);
        }catch(RuntimeException invalid){return false;}
    }

    /** GET-free, provider-free local display recovery; never starts generation. */
    private JsonObject recoverSavedHierarchy(PdfSource target,int ticket,String strategy,String selectedScope,int selectedPage,String fingerprint) {
        return recoverPartial(target,ticket,strategy,selectedScope,selectedPage,fingerprint);
    }

    private void showConcepts() { showConcepts(false); }
    private JsonObject conceptResultForDisplay() {
        String selectedScope=switch(scope.getSelectedIndex()){case 1->"page";case 2->"section";default->"document";};
        if(source==null || liveGenerationKey==null || liveConceptUnits.isEmpty()
                || !liveGenerationKey.equals(productKey(selectedScope,page)))return generated;
        JsonObject preview=new JsonObject();
        preview.addProperty("kind","partial");preview.addProperty("livePreview",true);
        preview.addProperty("documentId",source.id);preview.addProperty("strategy",summaryStrategyId());
        preview.addProperty("scope",selectedScope);preview.addProperty("page",selectedScope.equals("document")?0:page);
        JsonArray concepts=new JsonArray(),sections=new JsonArray();
        Map<String,JsonObject> nodes=new LinkedHashMap<>();boolean supplemented=false;
        for(JsonObject section:liveSummarySections.values()) {
            sections.add(section);
            if(section.has("standardKnowledgeUsed") && section.get("standardKnowledgeUsed").getAsBoolean())supplemented=true;
            if(section.has("hierarchy") && section.get("hierarchy").isJsonObject())
                for(JsonObject node:SummaryOutline.objects(section.getAsJsonObject("hierarchy"),"nodes"))
                    nodes.putIfAbsent(str(node,"id"),node);
        }
        // Unit files contain validated flat entries. Wrap each for the existing
        // card renderer; final canonical merging remains in the Python result.
        for(JsonArray unit:liveConceptUnits.values())for(JsonElement value:unit) {
            if(!value.isJsonObject())continue;
            JsonObject entry=value.getAsJsonObject();
            if(entry.has("entries")){concepts.add(entry);continue;}
            JsonObject card=new JsonObject();card.addProperty("name",str(entry,"name"));
            JsonArray entries=new JsonArray();entries.add(entry);card.add("entries",entries);concepts.add(card);
        }
        preview.add("concepts",concepts);preview.add("sections",sections);
        preview.addProperty("standardKnowledgeUsed",supplemented);
        if(!nodes.isEmpty()) {
            JsonObject hierarchy=new JsonObject();JsonArray items=new JsonArray();
            nodes.values().forEach(items::add);hierarchy.add("nodes",items);preview.add("hierarchy",hierarchy);
        }
        return preview;
    }
    private static String studyBackgroundNote(JsonObject result) {
        return result!=null && result.has("standardKnowledgeUsed") && result.get("standardKnowledgeUsed").getAsBoolean()
            ?"<p class='muted'>이해를 위한 표준 전공 개념 보충 포함 · 페이지 링크는 관련 자료 위치입니다.</p>":"";
    }
    private void showConcepts(boolean preserveScroll) {
        if(deferStudyView(conceptOverview)){conceptRenderPending=true;return;}
        conceptRenderPending=false;
        if(LayoutMotionPanel.defer(conceptScroll,"concepts",()->showConcepts(preserveScroll)))return;
        if(conceptOverview==null)return;
        JsonObject displayed=conceptResultForDisplay();
        String product=source==null?str(displayed==null?new JsonObject():displayed,"documentId"):source.id;
        product+="/"+(displayed==null?summaryStrategyId()+":"+scope.getSelectedIndex():resultProductKey(displayed));
        if(!conceptProduct.equals(product)){conceptCards.clear();conceptSelectionSources.clear();conceptProduct=product;}
        int fontSize=conceptFontSize.getValue();
        List<ConceptOverview.Card> cards=new ArrayList<>();Map<String,Integer> occurrences=new HashMap<>();
        for(JsonObject concept:SummaryOutline.objects(displayed,"concepts")) {
            String base=conceptIdentity(concept),key=product+"/concept/"+base+"/"+occurrences.merge(base,1,Integer::sum);
            JsonObject saved=concept.deepCopy();
            ConceptOverview.Card card=conceptCards.computeIfAbsent(key,k->new ConceptOverview.Card(k,conceptOverview,expandedConcepts.contains(k),
                open->{if(open)expandedConcepts.add(k);else expandedConcepts.remove(k);conceptSelection.refresh();},number->navigate("page:"+number)));
            String signature=saved.toString()+"/font/"+fontSize+conceptModuleState(saved,key);
            card.update(str(saved,"name"),conceptPages(saved),signature,()->createConceptDetails(saved,key,fontSize));cards.add(card);
        }
        Set<String> retained=new HashSet<>();for(var card:cards)retained.add(card.key);
        conceptCards.keySet().removeIf(key->!retained.contains(key));
        conceptSelectionSources.keySet().removeIf(key->retained.stream().noneMatch(id->conceptSelectionKey(key).startsWith(id+"/")));
        String message="개념을 펼치면 정의와 설명, 원문 근거를 함께 볼 수 있어요.";
        if(displayed==null)message="PDF 분석 후 개념을 생성해 주세요.";
        else if(displayed.has("livePreview"))message="개념 생성 중 · 완료된 구간부터 표시하고 있어요.";
        else if(str(displayed,"kind").equals("partial"))message=displayed.has("integrationPending")&&displayed.get("integrationPending").getAsBoolean()
            ?"구간별 개념을 복구했습니다 · 전체 강의 해설 통합 미완료":"완료된 구간의 개념만 표시합니다 · 전체 분석 미완료";
        else if(!isRegionStrategy(str(displayed,"strategy"))&&!currentVisualPages().equals(resultVisualPages(displayed)))message="그림 해석 결과가 추가됐습니다 · 개념 정리를 다시 생성하면 반영됩니다.";
        if(!studyBackgroundNote(displayed).isEmpty())message+=" 이해를 위한 표준 전공 개념 보충 포함 · 페이지 링크는 관련 자료 위치입니다.";
        conceptOverview.showCards(product,cards,message,ConceptOutline.groups(displayed));conceptSelection.refresh();
    }

    /** Display identity only. Identical names never merge cards or reuse summary occurrence IDs. */
    private static String conceptIdentity(JsonObject concept) {
        String explicit=str(concept,"conceptId");if(explicit.isEmpty())explicit=str(concept,"id");
        if(!explicit.isEmpty())return "id-"+UUID.nameUUIDFromBytes(explicit.getBytes(StandardCharsets.UTF_8));
        String anchor="";
        for(JsonObject entry:SummaryOutline.objects(concept,"entries")) {
            for(JsonObject evidence:SummaryOutline.objects(entry,"evidence"))if(!str(evidence,"sourceId").isEmpty()){anchor=str(evidence,"sourceId");break;}
            if(!anchor.isEmpty())break;
        }
        return UUID.nameUUIDFromBytes((str(concept,"name")+"\u0000"+anchor).getBytes(StandardCharsets.UTF_8)).toString();
    }
    private static List<Integer> conceptPages(JsonObject concept) {
        Set<Integer> pages=new TreeSet<>(citationPages(concept));
        if(concept.has("pages")&&concept.get("pages").isJsonArray())for(JsonElement p:concept.getAsJsonArray("pages"))try{if(p.getAsInt()>0)pages.add(p.getAsInt());}catch(RuntimeException ignored){}
        for(JsonObject entry:SummaryOutline.objects(concept,"entries"))pages.addAll(citationPages(entry));
        return List.copyOf(pages);
    }
    private String conceptModuleState(JsonObject concept,String key) {
        StringBuilder state=new StringBuilder();
        expandedSlideLens.stream().filter(k->k.startsWith(key+"/")).sorted().forEach(state::append);
        if(source!=null)for(JsonObject entry:SummaryOutline.objects(concept,"entries")){
            SlideLens.Request request=validatedSlideLens(entry);if(request==null)continue;
            String imageKey=source.id+"/"+request.regionId();state.append(imageKey).append(System.identityHashCode(slideLensImages.get(imageKey))).append(slideLensErrors.get(imageKey));
        }
        return state.toString();
    }
    private JComponent createConceptDetails(JsonObject concept,String conceptKey,int fontSize) {
        conceptSelectionSources.keySet().removeIf(key->conceptSelectionKey(key).startsWith(conceptKey+"/"));
        String conceptName=str(concept,"name");
        String cardOrigin=StudySelectionContext.lastOrigin(selectionOrigin(conceptSelectionSources,concept,conceptKey+"/origin",conceptName),null);
        JEditorPane details=html(true); StringBuilder body=new StringBuilder();
            Map<String,SlideLens.Request> conceptModules=new LinkedHashMap<>(); int entryNumber=0;
            Map<String,StepFlow.Model> conceptSequences=new LinkedHashMap<>();
            StringBuilder easyBody=new StringBuilder();
            Map<Integer,boolean[]> placedModules=new HashMap<>();
            JsonArray conceptEntries=concept.getAsJsonArray("entries");
            String currentField="";
            for(ConceptContent.Row display:ConceptContent.rows(conceptEntries,"definition","explanation","example","confusion")) {
                JsonObject c=display.entry();String key=display.field();
                String entryKey=conceptKey+"/entry-"+display.entryIndex();
                String origin=selectionOrigin(conceptSelectionSources,c,entryKey+"/"+key,conceptName);
                if(!key.equals(currentField)) {
                    String label=switch(key){case "definition"->"정의";case "explanation"->"설명";case "example"->"예시";default->"자주 혼동되는 점";};
                    body.append("<h4>").append(label).append(origin).append("</h4>");currentField=key;origin="";
                }
                body.append(conceptOrigin(renderWithSlideLens(studentText(c,key),entryKey,validatedSlideLens(c),conceptModules,
                    placedModules.computeIfAbsent(display.entryIndex(),ignored->new boolean[]{false}),fontSize),origin))
                    .append(citations(c)).append(visualCitations(c));
            }
            for(JsonElement entry:concept.getAsJsonArray("entries")) {
                JsonObject c=entry.getAsJsonObject();
                if(c.has("derivedFromSummary") && c.get("derivedFromSummary").getAsBoolean())
                    body.append("<p class='warning'>검증된 강의 해설에서 복구한 개념 초안입니다. 원본과 대조해 주세요.</p>");
                String entryKey=conceptKey+"/entry-"+entryNumber;
                StepFlow.Model sequence=StepFlow.resolve(c,index);
                if(sequence!=null)conceptSequences.put(entryKey+"/step-flow",sequence);
                SlideLens.Request request=validatedSlideLens(c);
                entryNumber++;
                boolean[] placed=placedModules.getOrDefault(entryNumber-1,new boolean[]{false});
                if(request!=null && !placed[0]) {
                    conceptModules.put(entryKey,request);
                    body.append("<!--SLIDELENS:").append(entryKey).append("-->");
                }
                if(sequence!=null)body.append("<!--SLIDELENS:").append(entryKey).append("/step-flow-->");
                else body.append(StepFlow.fallbackHtml(c,index,fontSize));
            }
            for(ConceptContent.Row display:ConceptContent.rows(conceptEntries,"easyExplanation")) {
                JsonObject c=display.entry();
                String origin=selectionOrigin(conceptSelectionSources,c,conceptKey+"/easy-"+display.entryIndex(),conceptName);
                easyBody.append(conceptOrigin(StudyMarkdown.renderWithScrollableMath(studentText(c,"easyExplanation"),fontSize),origin))
                    .append(citations(c)).append(visualCitations(c));
            }
            JPanel content=new JPanel(new BorderLayout());content.setBackground(Color.WHITE);
            JPanel detailStack=new JPanel();detailStack.setBackground(Color.WHITE);detailStack.setLayout(new BoxLayout(detailStack,BoxLayout.Y_AXIS));
            StudySelectionContext.inherit(detailStack,cardOrigin);
            appendConceptContent(detailStack,details,body.toString(),conceptModules,conceptSequences,fontSize);
            content.add(detailStack,BorderLayout.CENTER);
            JPanel bottom=new JPanel(new BorderLayout());bottom.setOpaque(false);
            JButton easyButton=null;
            if(!easyBody.isEmpty()) {
                boolean easyExpanded=expandedEasyConcepts.contains(conceptKey);
                easyButton=new JButton(easyExpanded?"쉬운 설명 접기":"쉬운 설명 보기");
                ConceptOverview.actionButton(easyButton,144,true);
                JPanel easyDetails=new JPanel();easyDetails.setBackground(Color.WHITE);
                easyDetails.setBorder(new LibraryDesign.RoundedBorder(8,MistWorkspaceTheme.LINE,new Insets(12,12,12,12)));
                StudySelectionContext.inherit(easyDetails,cardOrigin);
                easyDetails.setLayout(new BoxLayout(easyDetails,BoxLayout.Y_AXIS));
                appendConceptContent(easyDetails,html(true),easyBody.toString(),Map.of(),Map.of(),fontSize);
                JPanel easySpace=new JPanel(new BorderLayout());easySpace.setOpaque(false);
                easySpace.setBorder(new EmptyBorder(16,0,0,0));easySpace.add(easyDetails);
                ConceptOverview.Reveal easyReveal=new ConceptOverview.Reveal(easySpace,easyExpanded,conceptOverview);
                JButton easyToggle=easyButton;
                easyButton.addActionListener(e->{var anchor=conceptOverview.capture();boolean open=!easyReveal.isOpen();easyReveal.setOpen(open);
                    if(open)expandedEasyConcepts.add(conceptKey);else expandedEasyConcepts.remove(conceptKey);
                    easyToggle.setText(open?"쉬운 설명 접기":"쉬운 설명 보기");conceptList.revalidate();conceptList.repaint();conceptSelection.refresh();conceptOverview.restore(anchor);});
                bottom.add(easyReveal,BorderLayout.CENTER);
            }
            List<Integer> pages=conceptPages(concept);
            JButton sourceButton=pages.isEmpty()?null:ConceptOverview.sourceButton(pages,number->navigate("page:"+number));
            JButton tutorButton=new JButton("AI멘토에게 질문");ConceptOverview.actionButton(tutorButton,168,true);
            tutorButton.setIcon(MistWorkspaceTheme.icon("spark",16));
            tutorButton.setIconTextGap(8);
            tutorButton.addActionListener(e->navigate("ask:"+conceptName));
            bottom.add(ConceptOverview.actions(sourceButton,easyButton,tutorButton),BorderLayout.NORTH);
            content.add(bottom,BorderLayout.SOUTH);
        return content;
    }

    private static String conceptSelectionKey(String id) {
        if(!id.startsWith(StudySelectionContext.PREFIX))return "";
        try{return new String(Base64.getUrlDecoder().decode(id.substring(StudySelectionContext.PREFIX.length())),StandardCharsets.UTF_8);}
        catch(IllegalArgumentException ignored){return "";}
    }

    /** Keep hidden provenance inside its text block so Swing adds no empty paragraph. */
    private static String conceptOrigin(String html,String origin) {
        if(origin.isEmpty())return html;
        Matcher block=Pattern.compile("<(?:p|h[1-6]|li|td|th)(?:\\s[^>]*)?>").matcher(html);
        return block.find()?html.substring(0,block.end())+origin+html.substring(block.end()):origin+html;
    }

    static String conceptTitleHtml(String name,boolean expanded,int fontSize) {
        return "<html><b>"+(expanded?"－":"＋")+"&nbsp;&nbsp;"
            +StudyMarkdown.renderInline(name,fontSize)+"</b></html>";
    }

    private void appendConceptContent(JPanel stack,JEditorPane firstPane,String body,
                                      Map<String,SlideLens.Request> modules,
                                      Map<String,StepFlow.Model> sequences,int fontSize) {
        SummarySkin.FormulaPresentation presentation=SummarySkin.prepare(body);
        body=presentation.body();
        Matcher marker=SLIDE_LENS_MARKER.matcher(body);
        int start=0;boolean first=true;String origin=(String)stack.getClientProperty(StudySelectionContext.INHERITED);
        while(marker.find()) {
            String fragment=body.substring(start,marker.start());
            if(!fragment.isBlank()) {
                JEditorPane pane=first?firstPane:html(true);first=false;
                appendConceptProse(stack,pane,fragment,fontSize,origin);
            }
            origin=StudySelectionContext.lastOrigin(fragment,origin);
            // Reuse the summary's native grouped vectors, rounded emphasis and horizontal viewport.
            // The concept card caches this stack; width/animation changes never regenerate it.
            if(marker.group(4)!=null) {
                SummarySkin.FormulaGroup content=presentation.groups().get(marker.group(4));
                if(content!=null){
                    SummaryFormulaGroup group=new SummaryFormulaGroup(content,fontSize,this::navigate);
                    group.setAlignmentX(Component.LEFT_ALIGNMENT);
                    StudySelectionContext.inherit(group,origin);stack.add(group);
                }
                start=marker.end();continue;
            }
            if(marker.group(2)!=null) {
                StudyMarkdown.ScrollableMath equation=StudyMarkdown.scrollableMath(marker.group(2));
                if(equation!=null){MathScrollPane math=new MathScrollPane(equation,fontSize,false,true);StudySelectionContext.inherit(math,origin);stack.add(math);}
                start=marker.end();
                continue;
            }
            String key=marker.group(1);
            SlideLens.Request request=modules.get(key);
            if(request!=null)stack.add(slideLensPanel(request,key,()->showConcepts(true)));
            StepFlow.Model sequence=sequences.get(key);
            if(sequence!=null)stack.add(stepFlowPanel(sequence,key,fontSize));
            start=marker.end();
        }
        String remainder=body.substring(start);
        if(!remainder.isBlank() || first) {
            JEditorPane pane=first?firstPane:html(true);
            appendConceptProse(stack,pane,remainder,fontSize,origin);
        }
    }

    private void appendConceptProse(JPanel stack,JEditorPane pane,String body,int fontSize,String origin) {
        if(body.contains("<table ") || body.contains("<pre>")) {
            // Keep large tables/code accessible in narrow concept cards using the
            // same cached, selectable horizontal viewport as the summary formulas.
            SummaryFormulaGroup viewport=new SummaryFormulaGroup(new SummarySkin.FormulaGroup(body,false),fontSize,this::navigate);
            viewport.setAlignmentX(Component.LEFT_ALIGNMENT);StudySelectionContext.inherit(viewport,origin);stack.add(viewport);
            return;
        }
        ((StudyHtmlPane)pane).setReadingSkin(true);pane.setText(conceptDocumentHtml(body,fontSize));
        StudySelectionContext.inherit(pane,origin);
        pane.addHyperlinkListener(e->{if(e.getEventType()==javax.swing.event.HyperlinkEvent.EventType.ACTIVATED)navigate(e.getDescription());});
        pane.setAlignmentX(Component.LEFT_ALIGNMENT);stack.add(pane);
    }

    private static String conceptDocumentHtml(String body,int fontSize) {
        // The article already owns its horizontal padding. All typography, tables,
        // quotes, numbered lists and source chips share the summary's reading skin.
        return SummarySkin.formulaDocument(body,fontSize);
    }

    private JsonObject visualResult(PdfSource target,int number) {
        if(target==null || index==null) return null;
        Path path=target.folder.resolve(String.format(Locale.ROOT,"generated/visual-pages/page-%05d.json",number));
        if(Files.isRegularFile(path))try {
            JsonObject result=readJson(path);
            if(target.id.equals(str(result,"documentId")) && str(index,"fingerprint").equals(str(result,"sourceFingerprint")))return result;
        }catch(Exception ignored){}
        Path directory=path.getParent();
        if(Files.isDirectory(directory))try(var entries=Files.newDirectoryStream(directory,String.format(Locale.ROOT,"page-%05d-region-*.json",number))) {
            for(Path entry:entries)try {
                JsonObject result=readJson(entry);
                if(target.id.equals(str(result,"documentId")) && str(index,"fingerprint").equals(str(result,"sourceFingerprint")))return result;
            }catch(Exception ignored){}
        }catch(Exception ignored){}
        return null;
    }

    private void analyzeVisiblePage() {
        if(source==null || index==null || busy)return;
        JsonObject request=new JsonObject();JsonArray pages=new JsonArray();pages.add(page);request.add("pages",pages);
        preparePageAnalysis(request);
    }

    private void exitImageSelection() {
        if(!selectingImage)return;
        selectingImage=false;
        imageCanvas.setCursor(Cursor.getDefaultCursor());
        imageCanvas.repaint();
    }

    private void selectImageAt(Point point) {
        if(index==null || selectionPage<1 || selectionPage>pageLayouts.size())return;
        Rectangle pageBox=pageLayouts.get(selectionPage-1).bounds();
        if(!pageBox.contains(point)) {status.setText("파란 테두리로 표시된 PDF "+selectionPage+"쪽 이미지 안을 클릭하세요");return;}
        JsonArray regions=index.getAsJsonArray("pages").get(selectionPage-1).getAsJsonObject().getAsJsonArray("imageRegions");
        double x=(point.x-pageBox.x)/(double)pageBox.width,y=(point.y-pageBox.y)/(double)pageBox.height;
        int selected=-1;double smallest=Double.MAX_VALUE;
        for(int i=0;i<regions.size();i++) {
            JsonArray box=regions.get(i).getAsJsonObject().getAsJsonArray("bbox");
            double left=box.get(0).getAsDouble(),top=box.get(1).getAsDouble();
            double right=box.get(2).getAsDouble(),bottom=box.get(3).getAsDouble();
            double area=(right-left)*(bottom-top);
            if(x>=left&&x<=right&&y>=top&&y<=bottom&&area<smallest){selected=i;smallest=area;}
        }
        if(selected<0){status.setText("이미지 밖을 클릭했습니다 · 파란 테두리 안을 선택하세요");return;}
        exitImageSelection();
        requestImageExplanation(selectionPage,selected);
    }

    private void requestImageExplanation(int selectedPage,int regionIndex) {
        JsonObject request=new JsonObject();JsonArray pages=new JsonArray();pages.add(selectedPage);request.add("pages",pages);
        preparePageAnalysis(request);
    }

    private void prepareImageAnalysis() { preparePageAnalysis(new JsonObject()); }

    private void preparePageAnalysis(JsonObject request) {
        if(index==null || busy || source==null)return;
        request.addProperty("strategy","page-v1");
        runAi("vision-plan",request,null,plan->{
            if(plan.get("pending").getAsInt()==0) {
                try {index=readJson(source.folder.resolve("document.json"));}catch(Exception ignored){}
                updateOriginal();showImageAssessmentReport();
                status.setText("저장된 페이지 분석 재사용 · 새 요청 0회 · 확인 필요 "+plan.get("partial").getAsInt()+"쪽");
                return;
            }
            JPanel form=new JPanel();form.setLayout(new BoxLayout(form,BoxLayout.Y_AXIS));
            form.add(new JLabel("<html><body style='width:440px'>"+pagePlanHtml(plan)
                +"<br>현재 페이지 전체 이미지와 직접 추출 텍스트, 앞선 최대 3쪽의 짧은 문맥을 OpenAI에 보냅니다."
                +"<br>장식도 페이지에 함께 보이지만 별도 분석 요청은 만들지 않습니다."
                +"<br>완료·불완전 응답 모두 저장하며 자동 재호출하지 않습니다."
                +"<br>강의 해설은 강의 해설 생성 버튼에서 시작합니다.<br><br>이번 작업 비용 한도 (USD)</body></html>"));
            JSpinner budget=new JSpinner(new SpinnerNumberModel(.50,.01,1,.01));form.add(budget);
            if(JOptionPane.showConfirmDialog(this,form,"페이지 분석 · 외부 전송 및 비용 확인",
                JOptionPane.OK_CANCEL_OPTION,JOptionPane.PLAIN_MESSAGE)!=JOptionPane.OK_OPTION)return;
            long started=System.nanoTime();
            request.addProperty("retryMissingResponses",true);
            runAi("vision-auto",request,new CloudChoice("gpt-6-luna",((Number)budget.getValue()).doubleValue(),false),result->{
                displayImageAnalysis(result);
                showTimedReport(generationRunReportHtml(result),"페이지 분석 비용 · 이번 실행",started);
            });
        });
    }

    static String pagePlanHtml(JsonObject plan) {
        if(isRegionStrategy(str(plan,"strategy")))return "<b>"+escape(strategyLabel(str(plan,"strategy")))+" · GPT-6 Luna</b>"
            +"<br>선택 범위 "+plan.get("totalPages").getAsInt()+"쪽 · 로컬 이미지 추출 비용 없음"
            +String.format(Locale.ROOT,"<br>전체 생성 예상 비용: 약 $%.4f",plan.get("totalCostEstimateUsd").getAsDouble())
            +" · "+tutorCreditsHtml(plan.get("totalCostEstimateUsd").getAsDouble())
            +(plan.has("estimateLowUsd") && plan.has("estimateHighUsd")
                ?String.format(Locale.ROOT,"<br>예상 범위: $%.6f ~ $%.6f",plan.get("estimateLowUsd").getAsDouble(),plan.get("estimateHighUsd").getAsDouble()):"")
            +"<br>"+escape(str(plan,"estimateBasis"));
        String uncertain=plan.has("uncertainPreviousPages") && !plan.getAsJsonArray("uncertainPreviousPages").isEmpty()
            ?"<br>이전 유료 요청의 응답 미확인 페이지: "+escape(plan.get("uncertainPreviousPages").toString())+
                " · 확인을 누르면 응답 없는 요청을 이번 예산 안에서 1회 재시도합니다. 이전 요청과 중복 과금될 수 있습니다." : "";
        return "<b>"+("semantic-v1".equals(str(plan,"strategy"))?"PDF 강의 해설·개념 정리 생성":"페이지 전체 분석")
            +" · GPT-6 Luna</b><br>선택 범위 "+plan.get("total").getAsInt()+"쪽"
            +" · 저장된 결과 "+plan.get("cached").getAsInt()+"쪽 (확인 필요 "+plan.get("partial").getAsInt()+"쪽)"
            +"<br>결과 캐시 없는 페이지: "+plan.get("pending").getAsInt()+"건"
            +uncertain
            +String.format(Locale.ROOT,"<br>페이지 판독 예상 비용: 약 $%.4f",
                plan.get("costEstimateUsd").getAsDouble())
            +("semantic-v1".equals(str(plan,"strategy"))?"":" (강의 해설 생성 별도)")
            +("semantic-v1".equals(str(plan,"strategy"))
                ?String.format(Locale.ROOT,
                    "<br>연결·의미 단위 정리·강의 해설 예상 비용: 약 $%.4f<br>5%% 여유분 반영 (기본 예상치 × 1.05)<br><b>전체 생성 예상 비용: 약 $%.4f</b>",
                    plan.get("additionalCostEstimateUsd").getAsDouble(),
                    plan.get("totalCostEstimateUsd").getAsDouble())
                    +"<br>이 PDF의 글자·구성과 최근 완료 작업의 단계별 사용량을 바탕으로 추정했어요. 실제 응답 길이와 재시도에 따라 달라질 수 있어요."
                :"<br>완료된 판독의 평균 사용량으로 계산했어요. 실제 비용은 자료와 응답 길이에 따라 달라져요.");
    }

    private static boolean compatibleFingerprint(JsonObject result,JsonObject document) {
        String fingerprint=str(result,"sourceFingerprint");
        if(fingerprint.equals(str(document,"fingerprint")))return true;
        if(document.has("legacySourceFingerprints"))for(JsonElement old:document.getAsJsonArray("legacySourceFingerprints"))
            if(fingerprint.equals(old.getAsString()))return true;
        return false;
    }

    static String imageAnalysisRunReportHtml(JsonObject result) {
        JsonObject usage=result.getAsJsonObject("runUsage");
        if(usage==null)return "<html>이번 실행의 사용량 기록을 찾지 못했습니다.</html>";
        StringBuilder body=new StringBuilder("<html><body style='width:400px'><b>이번 실행의 Luna 이미지 분석</b><br><br>");
        int imageRequests=usage.get("imageRequests").getAsInt();
        int confirmedImages=usage.get("confirmedImageRequests").getAsInt();
        body.append("Luna 응답이 확인된 이미지 전송: <b>").append(confirmedImages)
            .append("회</b> · 이미지 포함 요청 시도 ").append(imageRequests).append("회<br>")
            .append("요청한 서로 다른 이미지 영역: ").append(usage.get("imageRegions").getAsInt()).append("개<br>")
            .append("이미지 없이 문맥만 판단한 요청: ").append(usage.get("textOnlyRequests").getAsInt()).append("회<br>")
            .append("중복 로고·장식 등 추가 호출 없이 제외: ").append(result.get("localZeroSkips").getAsInt()).append("개<br>")
            .append("분석 완료: ").append(result.get("completed").getAsInt()).append("/")
            .append(result.get("total").getAsInt()).append("개<br><br>")
            .append("API 사용량 기준 계산 비용: <b>$")
            .append(String.format(Locale.ROOT,"%.6f",usage.get("usageBasedUsd").getAsDouble())).append("</b><br>")
            .append("원화 환산(1달러 = 1,400원): 약 ")
            .append(estimatedKrw(usage.get("usageBasedUsd").getAsDouble())).append("원<br>")
            .append("입력 ").append(usage.get("inputTokens").getAsLong()).append(" / 출력 ")
            .append(usage.get("outputTokens").getAsLong()).append("토큰 · 총 ")
            .append(usage.get("inputTokens").getAsLong()+usage.get("outputTokens").getAsLong())
            .append("토큰<br>");
        int unknown=usage.get("unknownUsageRequests").getAsInt();
        if(imageRequests>confirmedImages)body.append("이미지 요청 ").append(imageRequests-confirmedImages)
            .append("회는 서버 응답이 없어 실제 전송 여부를 확인할 수 없습니다.<br>");
        if(unknown>0)body.append("<br>사용량 미확인 요청 ").append(unknown).append("회 · 별도 예약액 $")
            .append(String.format(Locale.ROOT,"%.6f",usage.get("uncertainReservedUsd").getAsDouble()))
            .append(" (실제 청구액 확인 필요)<br>");
        if(!str(result,"stopReason").isBlank())body.append("<br>").append(escape(str(result,"stopReason"))).append("<br>");
        body.append("<br><small>이미지 수는 이번 실행에서 이미지가 포함된 API 요청 횟수입니다. ")
            .append("금액은 반환된 토큰 사용량과 모델 단가로 계산했으며 실제 청구서와 다를 수 있습니다.</small></body></html>");
        return body.toString();
    }

    private void displayImageAnalysis(JsonObject result) {
        if(str(result,"kind").startsWith("page_analysis")) {
            try {index=readJson(source.folder.resolve("document.json"));}catch(Exception ignored){}
            updateOriginal();renderSummary(true);showConcepts();setControls();
            status.setText("페이지 분석 완료 · 확인 필요 "+result.get("partial").getAsInt()+"쪽");
            return;
        }
        imageReport.setEnabled(index!=null);
        for(JsonElement element:result.getAsJsonArray("explanations")) {
            JsonObject item=element.getAsJsonObject();String id=str(item,"regionId");
            visualNotices.put(id,item);
        }
        renderSummary();showConcepts();updateOriginal();
        String message="이미지 분석 "+result.get("completed").getAsInt()+"/"+result.get("total").getAsInt()+"개 · 학습용 설명 "
            +result.getAsJsonArray("explanations").size()+"개 · AI멘토에서 확인";
        if(result.has("skipped"))message+=" · 장식 등 제외 "+result.get("skipped").getAsInt()+"개";
        if(result.has("importanceCounts")) {
            JsonObject counts=result.getAsJsonObject("importanceCounts");
            message="이미지 중요도 · 0(생략) "+counts.get("0").getAsInt()+" · 1(보조) "+counts.get("1").getAsInt()
                +" · 2(핵심) "+counts.get("2").getAsInt()+" · 판단 보류 "+counts.get("undetermined").getAsInt()
                +" · 완료 "+result.get("completed").getAsInt()+"/"+result.get("total").getAsInt();
        }
        if(result.has("localZeroSkips"))message+=" · 추가 호출 없이 제외 "+result.get("localZeroSkips").getAsInt()+"개";
        if(result.has("accountedUsd"))message+=String.format(Locale.ROOT," · 이번 작업 기록 $%.5f",result.get("accountedUsd").getAsDouble());
        if(result.has("stopReason")&&!str(result,"stopReason").isBlank())message=str(result,"stopReason")+" ‘자료 페이지 분석’으로 이어서 진행할 수 있습니다.";
        status.setText(message);
        status.setToolTipText(message);
    }

    private void showVisualDetail(String id) {
        JsonObject result=visualNotices.get(id);if(result==null)return;
        int selectedPage=result.get("page").getAsInt();
        StringBuilder content=new StringBuilder("<p class='muted'>PDF ").append(pageLink(selectedPage))
            .append(" · GPT-6 Luna가 선택한 이미지에 대해 생성한 설명</p>")
            .append(imageAssessmentHtml(result))
            .append("<p class='warning'>그림 관찰과 문맥을 이용한 추론입니다. 숫자·기호·관계는 왼쪽 원본과 대조해 주세요.</p>")
            .append(StudyMarkdown.render(str(result,"description"),15));
        if(result.has("uncertainDetails") && !result.getAsJsonArray("uncertainDetails").isEmpty()) {
            content.append("<h3>확인이 필요한 부분</h3><ul>");
            for(JsonElement item:result.getAsJsonArray("uncertainDetails"))content.append("<li>").append(escape(item.getAsString())).append("</li>");
            content.append("</ul>");
        }
        visualDetail.setText(documentHtml("선택한 이미지 설명",content.toString(),15));
        visualDetail.setCaretPosition(0);
        studyColumns.showView("그림 설명");
    }

    static String imageAssessmentHtml(JsonObject result) {
        if(!result.has("importance"))return "";
        String label=result.get("importance").isJsonNull()?"판단 보류":switch(result.get("importance").getAsInt()) {
            case 0->"0 · 설명 생략";case 1->"1 · 이해 보조";case 2->"2 · 핵심 설명";default->"판단 보류";
        };
        List<String> purposes=new ArrayList<>();
        if(result.has("purposes"))for(JsonElement value:result.getAsJsonArray("purposes"))purposes.add(switch(value.getAsString()) {
            case "example"->"예시";case "understanding_aid"->"이해 보조";case "concept_explanation"->"개념 설명";
            case "evidence"->"근거 제시";case "comparison"->"비교";case "exercise"->"연습·문제";
            case "branding"->"로고·브랜딩";case "watermark"->"워터마크";case "decoration"->"장식";
            case "uncertain"->"판단 보류";default->"기타";
        });
        return "<p><b>이 페이지에서의 중요도: "+label+"</b><br>사용 목적(문맥상 추정): "+escape(String.join(" · ",purposes))
            +"</p><p class='muted'>"+escape(str(result,"roleReason"))
            +("fixed_repeat_cache".equals(str(result,"decisionSource"))?"<br>고정 반복 요소 · 추가 호출 없이 제외":"")
            +"<br>중요도는 페이지 이해에 필요한 정도이며 시험 출제 가능성을 뜻하지 않습니다.</p>";
    }

    private void showImageAssessmentReport() {
        JEditorPane report=html();
        StringBuilder body=new StringBuilder();
        if(index!=null)for(JsonElement p:index.getAsJsonArray("pages"))body.append(pageAnalysisHtml(p.getAsJsonObject()));
        report.setText(documentHtml("페이지 분석 결과",body.isEmpty()?"아직 페이지 분석 결과가 없습니다.":body.toString(),14));
        report.setCaretPosition(0);
        report.addHyperlinkListener(e->{if(e.getEventType()==javax.swing.event.HyperlinkEvent.EventType.ACTIVATED)navigate(e.getDescription());});
        JScrollPane scroll=new SmoothScrollPane(report);scroll.setPreferredSize(new Dimension(650,430));
        JOptionPane.showMessageDialog(this,scroll,"페이지별 학습 요소·수식·분석 상태",JOptionPane.PLAIN_MESSAGE);
    }

    static String imageAssessmentReportHtml(JsonArray assessments) {
        StringBuilder body=new StringBuilder("<p>0은 설명 생략, 1은 이해 보조, 2는 핵심 설명입니다. 판단 보류는 중요하지 않다는 뜻이 아닙니다.</p>");
        for(JsonElement element:assessments) {
            JsonObject item=element.getAsJsonObject();
            body.append("<h3>").append(pageLink(item.get("page").getAsInt())).append(" · 이미지 ")
                .append(item.get("regionIndex").getAsInt()+1).append("</h3>").append(imageAssessmentHtml(item)).append("<hr>");
        }
        return body.toString();
    }

    private void startGeneration() {
        startGeneration(0,false);
    }

    private static double comparisonNumber(JsonObject object,String key) {
        try{return object!=null && object.has(key)?object.get(key).getAsDouble():0;}
        catch(Exception ignored){return 0;}
    }

    private static String comparisonDuration(double seconds) {
        long rounded=Math.round(Math.max(0,seconds));
        return (rounded/60)+"분 "+String.format(Locale.ROOT,"%02d",rounded%60)+"초";
    }

    private static void appendComparisonBlock(StringBuilder body,JsonObject block,int fontSize) {
        if(block==null)return;
        String title=str(block,"title");
        if(!title.isBlank())body.append("<h3>").append(escape(title)).append("</h3>");
        body.append(StudyMarkdown.render(str(block,"body"),fontSize));
        String easy=str(block,"easyExplanation");
        if(!easy.isBlank())body.append("<p class='muted'><b>쉬운 설명</b></p>")
            .append(StudyMarkdown.render(easy,fontSize));
        if(block.has("parts") && block.get("parts").isJsonArray())
            for(JsonElement item:block.getAsJsonArray("parts"))if(item.isJsonObject())appendComparisonBlock(body,item.getAsJsonObject(),fontSize);
        if(block.has("evidence") && block.get("evidence").isJsonArray()) {
            Set<Integer> pages=new TreeSet<>();
            for(JsonElement item:block.getAsJsonArray("evidence"))if(item.isJsonObject()) {
                JsonObject evidence=item.getAsJsonObject();
                if(evidence.has("page"))try{pages.add(evidence.get("page").getAsInt());}catch(Exception ignored){}
            }
            if(!pages.isEmpty()) {
                body.append("<p class='muted'>PDF 근거: ");
                for(int number:pages)body.append(pageLink(number)).append(" &nbsp; ");
                body.append("</p>");
            }
        }
    }

    static String comparisonVariantHtml(JsonObject variant) {
        StringBuilder body=new StringBuilder();
        String state=str(variant,"status");
        String stateLabel=switch(state){case "complete"->"완료";case "budget_exhausted"->"비용 한도 도달";
            case "skipped_due_to_budget"->"합산 비용 한도로 실행하지 않음";
            case "failed"->"실패";default->state;};
        body.append("<p><b>상태:</b> ").append(escape(stateLabel))
            .append("<br><b>승인 후 실행 시간:</b> ").append(comparisonDuration(comparisonNumber(variant,"seconds")))
            .append("<br>글자 추출 ").append(comparisonDuration(comparisonNumber(variant,"extractionSeconds")))
            .append(" · 분석·강의 해설 생성 ").append(comparisonDuration(comparisonNumber(variant,"generationSeconds")))
            .append("</p>");
        if(variant.has("extractionCached") && variant.get("extractionCached").getAsBoolean())
            body.append("<p class='muted'>글자 추출 캐시 재사용</p>");
        JsonObject usage=variant.has("usage")&&variant.get("usage").isJsonObject()?variant.getAsJsonObject("usage"):null;
        if(usage!=null) {
            body.append("<p><b>이번 실행의 API 사용량 기준 비용: $")
                .append(String.format(Locale.ROOT,"%.6f",comparisonNumber(usage,"usageBasedUsd")))
                .append("</b><br>새 API 요청 ").append((int)comparisonNumber(usage,"requests"))
                .append("회 · 입력 ").append((long)comparisonNumber(usage,"inputTokens"))
                .append(" / 출력 ").append((long)comparisonNumber(usage,"outputTokens"))
                .append("토큰 · 총 ").append((long)(comparisonNumber(usage,"inputTokens")
                    +comparisonNumber(usage,"outputTokens"))).append("토큰</p>");
            if(comparisonNumber(usage,"unknownUsageRequests")>0)
                body.append("<p class='warning'>사용량 미확인 요청 ")
                    .append((int)comparisonNumber(usage,"unknownUsageRequests"))
                    .append("회 · 예약액 $")
                    .append(String.format(Locale.ROOT,"%.6f",comparisonNumber(usage,"uncertainReservedUsd")))
                    .append(" · 실제 청구 확인 필요</p>");
            if(comparisonNumber(usage,"requests")==0)body.append("<p class='muted'>완료 캐시 재사용 · 이번 실행의 새 API 비용 0</p>");
        }
        JsonObject cumulative=variant.has("cumulativeUsage")&&variant.get("cumulativeUsage").isJsonObject()
            ?variant.getAsJsonObject("cumulativeUsage"):null;
        if(cumulative!=null)body.append("<p><b>이 방식 누적 API 사용량 기준 비용: $")
            .append(String.format(Locale.ROOT,"%.6f",comparisonNumber(cumulative,"usageBasedUsd")))
            .append("</b> · 누적 요청 ").append((int)comparisonNumber(cumulative,"requests"))
            .append("회</p>");
        if(cumulative!=null && comparisonNumber(cumulative,"uncertainReservedUsd")>0)
            body.append("<p class='warning'>이 방식 누적 사용량 미확인 예약액 $")
                .append(String.format(Locale.ROOT,"%.6f",comparisonNumber(cumulative,"uncertainReservedUsd")))
                .append("</p>");
        if(variant.has("extractionFallbackPages") && variant.get("extractionFallbackPages").isJsonArray()
                && !variant.getAsJsonArray("extractionFallbackPages").isEmpty())
            body.append("<p class='warning'>글자 추출 실패·대체 페이지 있음. 해당 페이지 원문을 확인하세요.</p>");
        if(variant.has("error"))body.append("<p class='warning'>").append(escape(str(variant,"error"))).append("</p>");
        JsonObject result=variant.has("result")&&variant.get("result").isJsonObject()?variant.getAsJsonObject("result"):null;
        if(result!=null) {
            if(result.has("skippedStudyPages") && !result.getAsJsonArray("skippedStudyPages").isEmpty())
                body.append("<p class='muted'>학습 내용이 없어 제외한 페이지: ")
                    .append(escape(result.getAsJsonArray("skippedStudyPages").toString())).append("</p>");
            if(result.has("incompleteStudyPages") && !result.getAsJsonArray("incompleteStudyPages").isEmpty())
                body.append("<p class='warning'>학습 내용 반영 여부를 확인할 페이지: ")
                    .append(escape(result.getAsJsonArray("incompleteStudyPages").toString()))
                    .append(". 해당 페이지는 원본과 대조해 주세요.</p>");
            body.append("<hr><h2>전체 강의 해설</h2>");
            appendComparisonBlock(body,result.getAsJsonObject("overview"),16);
            if(result.has("sections") && result.get("sections").isJsonArray()) {
                body.append("<h2>페이지별 정리</h2>");
                for(JsonElement item:result.getAsJsonArray("sections"))if(item.isJsonObject())appendComparisonBlock(body,item.getAsJsonObject(),16);
            }
            if(result.has("concepts") && result.get("concepts").isJsonArray()) {
                body.append("<h2>개념 정리</h2>");
                for(JsonElement item:result.getAsJsonArray("concepts"))if(item.isJsonObject()) {
                    JsonObject concept=item.getAsJsonObject();
                    body.append("<h3>").append(escape(str(concept,"name"))).append("</h3>");
                    if(concept.has("entries") && concept.get("entries").isJsonArray())
                        for(JsonElement entry:concept.getAsJsonArray("entries"))if(entry.isJsonObject()) {
                            JsonObject detail=entry.getAsJsonObject();
                            if(detail.has("derivedFromSummary") && detail.get("derivedFromSummary").getAsBoolean())
                                body.append("<p class='warning'>검증된 강의 해설에서 복구한 개념 초안입니다. 원본과 대조해 주세요.</p>");
                            for(String key:new String[]{"definition","explanation","easyExplanation","example","confusion"})
                                body.append(StudyMarkdown.render(str(detail,key),16));
                        }
                }
            }
        }
        return documentHtml(str(variant,"label")+" · 전체 강의 해설 비교",body.toString(),16);
    }

    private void showComparisonDialog() {
        JsonObject report=comparisonReport;
        if(report==null || !report.has("variants"))return;
        JDialog dialog=new JDialog(SwingUtilities.getWindowAncestor(this),"PDF 추출 방식 비교 결과",Dialog.ModalityType.APPLICATION_MODAL);
        dialog.setLayout(new BorderLayout(8,8));
        JLabel totals=new JLabel("<html><b>두 방식 합계</b> · 승인 후 "
            +comparisonDuration(comparisonNumber(report,"totalSeconds"))+" · 이번 실행 API 사용량 기준 $"
            +String.format(Locale.ROOT,"%.6f",comparisonNumber(report,"usageBasedUsd"))
            +(comparisonNumber(report,"uncertainReservedUsd")>0?" · 사용량 미확인 예약액 $"
                +String.format(Locale.ROOT,"%.6f",comparisonNumber(report,"uncertainReservedUsd")):"")
            +(report.has("cumulativeUsageBasedUsd")?"<br>두 방식 누적 API 사용량 기준 $"
                +String.format(Locale.ROOT,"%.6f",comparisonNumber(report,"cumulativeUsageBasedUsd")):"")
            +(comparisonNumber(report,"cumulativeUncertainReservedUsd")>0?" · 누적 사용량 미확인 예약액 $"
                +String.format(Locale.ROOT,"%.6f",comparisonNumber(report,"cumulativeUncertainReservedUsd")):"")
            +"<br><small>각 탭에서 시간·비용·강의 해설 결과를 볼 수 있습니다. 실제 청구 금액은 공급자 기록이 기준입니다.</small></html>");
        totals.setBorder(new EmptyBorder(12,16,8,16));dialog.add(totals,BorderLayout.NORTH);
        JTabbedPane methods=new JTabbedPane();
        for(JsonElement item:report.getAsJsonArray("variants"))if(item.isJsonObject()) {
            JsonObject variant=item.getAsJsonObject();
            JEditorPane pane=html();pane.setText(comparisonVariantHtml(variant));pane.setCaretPosition(0);
            pane.addHyperlinkListener(event->{if(event.getEventType()==javax.swing.event.HyperlinkEvent.EventType.ACTIVATED)navigate(event.getDescription());});
            methods.addTab(str(variant,"label"),new SmoothScrollPane(pane));
        }
        dialog.add(methods,BorderLayout.CENTER);
        dialog.setSize(980,720);dialog.setLocationRelativeTo(this);dialog.setVisible(true);
    }

    private void showSemanticCoverage() {
        if(generated==null || !generated.has("coverage"))return;
        StringBuilder body=new StringBuilder("<html><body><h2>원문 처리 내역</h2><p>반영 상태와 판정 사유를 확인할 수 있어요. 페이지 번호를 누르면 원문으로 이동해요.</p><table cellpadding='7'><tr><th>페이지</th><th>상태</th><th>사유</th></tr>");
        for(JsonElement item:generated.getAsJsonArray("coverage")) {
            JsonObject entry=item.getAsJsonObject();
            String state=switch(str(entry,"state")) {
                case "summarized"->"강의 해설 반영";case "integrated"->"반복 과정으로 통합";
                case "context"->"문단 제목으로 연결";case "excluded"->"제외";case "needs_review"->"확인 필요";
                case "context_only"->"앞뒤 문맥";default->"강의 해설 대기";
            };
            body.append("<tr><td>").append(pageLink(entry.get("page").getAsInt())).append("</td><td>")
                .append(state).append("</td><td>").append(escape(str(entry,"reason"))).append("</td></tr>");
        }
        body.append("</table></body></html>");JEditorPane pane=html();pane.setText(body.toString());pane.setCaretPosition(0);
        pane.addHyperlinkListener(event->{if(event.getEventType()==javax.swing.event.HyperlinkEvent.EventType.ACTIVATED)navigate(event.getDescription());});
        JDialog dialog=new JDialog(SwingUtilities.getWindowAncestor(this),"의미 단위 처리 내역",Dialog.ModalityType.MODELESS);
        dialog.add(new SmoothScrollPane(pane));dialog.setSize(800,620);dialog.setLocationRelativeTo(this);dialog.setVisible(true);
    }

    private void showStrategyComparison() {
        if(source==null || index==null)return;
        String selected=switch(scope.getSelectedIndex()){case 1->"page";case 2->"section";default->"document";};
        int selectedPage=selected.equals("document")?0:selected.equals("section")?(page-1)/5*5+1:page;
        JDialog dialog=new JDialog(SwingUtilities.getWindowAncestor(this),"방식별 저장 결과 비교",Dialog.ModalityType.MODELESS);
        JTabbedPane columns=new JTabbedPane();
        String[] ids=STRATEGY_IDS;String[] labels=STRATEGY_LABELS;
        for(int i=0;i<ids.length;i++) {
            JsonObject result=products.get(strategyProductKey(ids[i],selected,selectedPage));
            StringBuilder body=new StringBuilder("<html><body><h2>").append(labels[i]).append("</h2>");
            if(result==null)body.append("<p>이 범위의 저장된 결과가 없어요. 처리 방식을 선택해서 생성해 주세요.</p>");
            else {
                body.append("<p>모델: ").append(escape(str(result,"model")))
                    .append("<br>강의 해설 단위: ").append(result.getAsJsonArray("sections").size()).append("개</p>");
                JsonObject usage=result.has("generationUsage")?result.getAsJsonObject("generationUsage"):result.has("runUsage")?result.getAsJsonObject("runUsage"):null;
                if(usage!=null)body.append("<p>저장된 실행 기록 · $")
                    .append(String.format(Locale.ROOT,"%.6f",comparisonNumber(usage,"usageBasedUsd")))
                    .append("<br>입력 ").append((long)comparisonNumber(usage,"inputTokens"))
                    .append(" / 출력 ").append((long)comparisonNumber(usage,"outputTokens"))
                    .append(" / 캐시 입력 ").append((long)comparisonNumber(usage,"cachedInputTokens"))
                    .append("토큰</p>");
                else body.append("<p>이전 결과에 실행 비용이 저장되어 있지 않아요.</p>");
                if(result.has("metrics"))body.append("<p>처리 시간: ").append(comparisonDuration(comparisonNumber(result.getAsJsonObject("metrics"),"elapsedSeconds"))).append("</p>");
                if(result.has("coverageComplete") && !result.get("coverageComplete").getAsBoolean())body.append("<p>원문 반영·판독 확인이 필요한 부분이 있어요.</p>");
                for(JsonElement item:result.getAsJsonArray("sections")) {
                    JsonObject section=item.getAsJsonObject().deepCopy();
                    if(section.has("parts") && !section.getAsJsonArray("parts").isEmpty())section.addProperty("body","");
                    appendComparisonBlock(body,section,16);
                }
            }
            body.append("</body></html>");JEditorPane pane=html();pane.setText(body.toString());pane.setCaretPosition(0);
            pane.addHyperlinkListener(event->{if(event.getEventType()==javax.swing.event.HyperlinkEvent.EventType.ACTIVATED)navigate(event.getDescription());});
            columns.addTab(labels[i],new SmoothScrollPane(pane));
        }
        JLabel note=new JLabel("<html>저장된 결과만 비교해요 · 새 API 호출 없음<br>기존 판독 재사용 여부와 실행 횟수가 다르면 비용을 같은 조건의 절감률로 비교할 수 없어요.</html>");
        note.setBorder(new EmptyBorder(10,12,10,12));dialog.add(note,BorderLayout.NORTH);dialog.add(columns,BorderLayout.CENTER);
        dialog.setSize(1200,780);dialog.setLocationRelativeTo(this);dialog.setVisible(true);
    }

    private void startGeneration(long preparationNanos) {
        startGeneration(preparationNanos,false);
    }

    private static JsonObject savedGeneration(Path folder,String documentId,JsonObject document,
                                               String strategy,String selectedScope,int selectedPage,JsonObject fallback) {
        JsonObject cached=fallback;
        int normalizedPage=selectedScope.equals("document")?0:selectedScope.equals("section")?(selectedPage-1)/5*5+1:selectedPage;
        Path latest=folder.resolve(strategyFolder(strategy)).resolve("latest-"+selectedScope+"-"+normalizedPage+".json");
        try {cached=readJson(latest);}catch(Exception ignored) { /* The in-memory result may still be usable. */ }
        return completeGeneration(cached,documentId,document)?cached:null;
    }

    private static boolean completeGeneration(JsonObject cached,String documentId,JsonObject document) {
        if(cached==null)return false;
        return "ai_generated".equals(str(cached,"kind")) && documentId.equals(str(cached,"documentId"))
            && compatibleFingerprint(cached,document) && cached.has("sections") && cached.has("concepts");
    }

    private void startGeneration(long preparationNanos,boolean forceNew) {
        startGeneration(preparationNanos,forceNew,true);
    }

    private void startAutomaticStudy(long preparationNanos,boolean retryMissingResponses) {
        if(closed || source==null || index==null || busy || externalBatchActive)return;
        selectGenerationEngine(PdfStudyStrategy.DEFAULT);
        scope.setSelectedIndex(0);
        if(completeGeneration(generated,source.id,index)) {
            showSavedGeneration(generated);
            return;
        }
        startGeneration(preparationNanos,false,retryMissingResponses);
    }

    private void startGeneration(long preparationNanos,boolean forceNew,boolean retryMissingResponses) {
        if(closed || index==null || busy || externalBatchActive)return;
        if(!generationEngineSelected && !chooseGenerationEngine())return;

        JsonObject request=new JsonObject();
        request.addProperty("scope",switch(scope.getSelectedIndex()){case 1->"page";case 2->"section";default->"document";});
        request.addProperty("page",scope.getSelectedIndex()==0?0:page);
        request.addProperty("strategy",summaryStrategyId());
        if(!forceNew) {
            PdfSource target=source;JsonObject document=index;
            int epoch=generation.get();
            JsonObject fallback=products.get(productKey(str(request,"scope"),request.get("page").getAsInt()));
            setBusy(true,"저장된 강의 해설·개념 정리 확인 중…");
            jobs.execute(()->{
                JsonObject cached=savedGeneration(target.folder,target.id,document,str(request,"strategy"),
                    str(request,"scope"),request.get("page").getAsInt(),fallback);
                onEdt(epoch,()->{
                    if(source!=target)return;
                    setBusy(false,"강의 해설 준비 중…");
                    if(cached!=null) {
                        products.put(strategyProductKey(str(request,"strategy"),str(request,"scope"),request.get("page").getAsInt()),cached);
                        showSavedGeneration(cached);
                    } else startGenerationPlan(request,preparationNanos,retryMissingResponses);
                });
            });
            return;
        }
        startGenerationPlan(request,preparationNanos,retryMissingResponses);
    }

    private void showSavedGeneration(JsonObject result) {
        int pending=pendingStudyPageCount(result);
        status.setText("저장된 강의 해설·개념 정리 불러옴 · 새 API 비용 없음"
            +(pending>0?" · 원문 확인 필요 "+pending+"쪽":""));
        setGenerationProgress(new GenerationProgress(source.id,source.name,100,
            "저장된 강의 해설·개념 정리 불러옴",true,false,pending>0));
        selectProduct();showTab("요약");renderSummary();fadeInSavedSummary();showConcepts();setControls();
    }

    private void startGenerationPlan(JsonObject request,long preparationNanos,boolean retryMissingResponses) {
        admitStudyGeneration(()->startAdmittedGenerationPlan(request,preparationNanos,retryMissingResponses));
    }

    private void startAdmittedGenerationPlan(JsonObject request,long preparationNanos,boolean retryMissingResponses) {
        status.setText("생성 계획과 예상 사용량을 계산하고 있어요.");
        setGenerationProgress(new GenerationProgress(source.id,source.name,0,"강의 해설 준비 중",false,false));
        JsonObject planRequest=new JsonObject();JsonArray pages=new JsonArray();
        planRequest.addProperty("scope",str(request,"scope"));
        planRequest.addProperty("page",request.get("page").getAsInt());
        String selectedScope=str(request,"scope");int selectedPage=request.get("page").getAsInt();
        int first=selectedScope.equals("document")?1:selectedScope.equals("page")?selectedPage:(selectedPage-1)/5*5+1;
        int last=selectedScope.equals("document")?source.count:selectedScope.equals("page")?selectedPage:Math.min(source.count,first+4);
        if(str(request,"strategy").equals(SEMANTIC_VERSION) && !selectedScope.equals("document")){first=Math.max(1,first-1);last=Math.min(source.count,last+1);}
        for(int n=first;n<=last;n++)pages.add(n);planRequest.add("pages",pages);
        planRequest.addProperty("strategy",summaryStrategyId());
        planRequest.addProperty("retryMissingResponses",retryMissingResponses);
        long planStarted=System.nanoTime();
        boolean groupPlan=PdfStudyStrategy.selectable(summaryStrategyId());
        runAi(groupPlan?"group-plan":"vision-plan",planRequest,
            groupPlan?new CloudChoice("gpt-6-luna",1.0,false):null,plan->{
            long processingNanos=preparationNanos+System.nanoTime()-planStarted;
            double estimatedUsd=plan.has("totalCostEstimateUsd")?plan.get("totalCostEstimateUsd").getAsDouble():0;
            long estimatedTokens=plan.has("estimatedTotalTokens")?plan.get("estimatedTotalTokens").getAsLong():0;
            request.addProperty("approvedEstimateUsd",estimatedUsd);
            request.addProperty("estimatedTotalTokens",estimatedTokens);
            if(plan.has("planningRunUsage") && plan.get("planningRunUsage").isJsonObject())
                request.add("planningRunUsage",plan.getAsJsonObject("planningRunUsage").deepCopy());
            if(plan.has("pendingOriginalUsage") && plan.get("pendingOriginalUsage").isJsonObject())
                request.add("pendingOriginalUsage",plan.getAsJsonObject("pendingOriginalUsage").deepCopy());
            for(String field:new String[]{"estimateLowUsd","estimateHighUsd","estimateBasis","estimateVersion"})
                if(plan.has(field))request.add(field,plan.get(field).deepCopy());
            startGeneration(request,new CloudChoice("gpt-6-luna",1.0,false),processingNanos,retryMissingResponses);
        });
    }

    private void startGeneration(JsonObject request,CloudChoice choice,long preparationNanos,boolean retryMissingResponses) {
        boolean pendingOriginals=request.has("pendingOriginalUsage")
            && request.get("pendingOriginalUsage").isJsonObject()
            && request.getAsJsonObject("pendingOriginalUsage").has("requests")
            && request.getAsJsonObject("pendingOriginalUsage").get("requests").getAsInt()>0;
        boolean missing=pendingOriginals;
        if(generated!=null && generated.has("failedUnits") && generated.get("failedUnits").isJsonArray()) {
            for(JsonElement item:generated.getAsJsonArray("failedUnits"))
                if(item.isJsonObject() && "MissingPaidResponseError".equals(str(item.getAsJsonObject(),"error")))missing=true;
        }
        if(missing && retryMissingResponses) {
                int decision=JOptionPane.showConfirmDialog(this,
                    "완료된 설명은 그대로 보존하고 이전 요청의 결과를 먼저 조회해요.\n"
                    +"복구하지 못한 구간만 다시 생성하며 추가 비용이 발생할 수 있어요.\n"
                    +"이전 요청의 미확정 비용은 별도로 유지돼요. 계속할까요?",
                    "미완료 구간 복구·재생성",JOptionPane.OK_CANCEL_OPTION,JOptionPane.QUESTION_MESSAGE);
                if(decision!=JOptionPane.OK_OPTION){finishGeneration(true,"미완료 구간은 보존했어요.");return;}
                request.addProperty("retryUnresolvedResponses",true);
        }
        request.addProperty("retryMissingResponses",retryMissingResponses);
        pendingGenerationReport=null;
        clearLiveSummary();
        liveGenerationKey=productKey(str(request,"scope"),request.get("page").getAsInt());
        int initial=generationProgress!=null && !generationProgress.finished()
            ?generationProgress.percent():0;
        setGenerationProgress(new GenerationProgress(source.id,source.name,initial,"강의 해설 준비 중",false,false));
        showTab("요약");renderSummary(true);
        long started=System.nanoTime();
        runAi("generate",request,choice,result->{
            products.put(resultProductKey(result),result);
            selectProduct();renderSummary(true);if(result.has("cacheHit") && result.get("cacheHit").getAsBoolean())fadeInSavedSummary();showConcepts();setControls();
            boolean partial="partial".equals(str(result,"kind"));
            int pending=pendingStudyPageCount(result);
            status.setText(partial?"강의 해설 일부 완료 · 남은 영역 확인 필요"
                :pending>0?"강의 해설 생성 완료 · 원문 확인 필요 "+pending+"쪽":"강의 해설·개념 정리 완료");
            finishGeneration(partial,!partial && pending>0,partial
                ?"완료된 설명을 저장했어요 · 남은 영역은 다시 생성할 수 있어요."
                :pending>0?"강의 해설 생성 완료 · 원문 확인 필요 "+pending+"쪽":"강의 해설·개념 정리 완료");
            if(result.has("creditStopped") && result.get("creditStopped").getAsBoolean()) {
                finishGeneration(true,"크레딧 부족으로 생성 중단");
                status.setText("크레딧 부족으로 생성 중단 · 완료된 강의 해설은 보관됐어요.");
                if(automaticStudy)showGenerationError("크레딧이 부족해서 강의 해설 생성이 중단됐어요.");
                else if(isShowing())CreditShortageDialog.show(this,"크레딧이 부족해서 강의 해설/개념 정리 생성이 중단됐어요. 완료된 내용은 보관했어요.");
            }
            if(!automaticStudy && (!result.has("cacheHit") || !result.get("cacheHit").getAsBoolean()))
                showTimedReport(generationRunReportHtml(result,request),
                    "PDF 분석·강의 해설 생성 비용 · 이번 실행",started,preparationNanos);
        });
    }

    static String generationRunReportHtml(JsonObject result) {
        return generationRunReportHtml(result,null);
    }

    static String generationRunReportHtml(JsonObject result,JsonObject request) {
        return GenerationCostReport.html(result,request);
    }

    private static String estimatedKrw(double usd) {
        return String.format(Locale.KOREA,"%,.1f",usd*1400);
    }

    private void rememberTutorAnswer(String marker,JsonObject result){
        if(tutorAnswers.containsKey(marker))return;
        tutorMemory=result.has("memory")?result.getAsJsonObject("memory").deepCopy():new JsonObject();
        tutorAnswers.put(marker,result.deepCopy());
        conversation.stream().filter(turn->turn.marker.equals(marker)).findFirst().ifPresent(turn->turn.answeredAt=System.currentTimeMillis());
        saveTutorConversation();
    }
    private void saveTutorConversation(){
        if(source==null||closed)return;
        Path folder=source.folder;
        JsonObject snapshot=new JsonObject();snapshot.add("memory",tutorMemory.deepCopy());
        JsonArray turns=new JsonArray();
        Map<String,List<TutorPreview>> previews=new HashMap<>();
        for(TutorTurn turn:conversation){
            JsonObject value=new JsonObject();value.addProperty("question",turn.question);value.addProperty("marker",turn.marker);
            value.addProperty("studySelection",turn.studySelection);value.addProperty("answeredAt",turn.answeredAt);
            if(turn.failure!=null)value.addProperty("failure",turn.failure);
            JsonObject answer=tutorAnswers.get(turn.marker);if(answer!=null)value.add("result",answer.deepCopy());
            turns.add(value);previews.put(turn.marker,List.copyOf(turn.previews));
        }
        snapshot.add("turns",turns);
        files.execute(()->{
            try{
                for(JsonElement element:turns){
                    JsonObject turn=element.getAsJsonObject();JsonArray images=new JsonArray();
                    for(TutorPreview preview:previews.get(turn.get("marker").getAsString())){
                        JsonObject image=new JsonObject();image.addProperty("name",preview.name());
                        if(preview.icon()!=null){
                            ImageIcon icon=preview.icon();BufferedImage pixels=new BufferedImage(icon.getIconWidth(),icon.getIconHeight(),BufferedImage.TYPE_INT_ARGB);
                            Graphics2D graphics=pixels.createGraphics();graphics.drawImage(icon.getImage(),0,0,null);graphics.dispose();
                            try(var output=new java.io.ByteArrayOutputStream()){
                                ImageIO.write(pixels,"png",output);image.addProperty("png",Base64.getEncoder().encodeToString(output.toByteArray()));
                            }finally{pixels.flush();}
                        }
                        images.add(image);
                    }
                    turn.add("previews",images);
                }
                TutorConversationStore.write(folder,snapshot);
            }catch(Exception failure){SwingUtilities.invokeLater(()->{
                if(!closed&&source!=null&&source.folder.equals(folder))status.setText("AI멘토 대화 저장을 완료하지 못했어요. 현재 대화는 유지돼요.");
            });}
        });
    }
    private void restoreTutorConversation(JsonObject saved){
        resetTutor();
        if(!saved.has("turns"))return;
        tutorMemory=saved.getAsJsonObject("memory").deepCopy();
        for(JsonElement element:saved.getAsJsonArray("turns")){
            JsonObject value=element.getAsJsonObject();List<TutorPreview> previews=new ArrayList<>();
            if(value.has("previews"))for(JsonElement item:value.getAsJsonArray("previews")){
                JsonObject image=item.getAsJsonObject();ImageIcon icon=null;
                if(image.has("png"))try{icon=new ImageIcon(Base64.getDecoder().decode(image.get("png").getAsString()));}
                catch(IllegalArgumentException invalid){/* Keep the attachment label if its thumbnail is damaged. */}
                previews.add(new TutorPreview(str(image,"name"),icon));
            }
            TutorTurn turn=new TutorTurn(str(value,"question"),str(value,"marker"),previews,value.has("studySelection")&&value.get("studySelection").getAsBoolean());
            if(value.has("failure"))turn.failure=str(value,"failure");
            if(value.has("answeredAt"))turn.answeredAt=value.get("answeredAt").getAsLong();
            conversation.add(turn);
            if(value.has("result"))tutorAnswers.put(turn.marker,value.getAsJsonObject("result").deepCopy());
        }
        renderTutor(false);
    }

    private void confirmNewTutorChat(){
        if(tutorBusy)return;
        PdfSource target=source;
        Object[] options={"삭제 후 새 채팅","취소하기"};
        int selected=JOptionPane.showOptionDialog(this,"새 채팅을 누르면 이 대화기록이 삭제돼요 !",
            "새 채팅",JOptionPane.DEFAULT_OPTION,JOptionPane.WARNING_MESSAGE,null,options,options[1]);
        if(source==target)startNewTutorChat(selected);
    }
    private void startNewTutorChat(int selected){
        if(tutorBusy||selected!=0)return;
        resetTutor();saveTutorConversation();
    }

    private void resetTutor() {
        tutorResizeTimer.stop();tutorBubbles.clear();
        tutorTimeTimer.stop();tutorTimeLabels.clear();likedTutorAnswers.clear();tutorFollowUps.clear();
        tutorMemory=new JsonObject(); conversation.clear(); tutorAnswers.clear(); expandedTutorEvidence.clear();
        activeTutorMarker=null;clearTutorStream();question.setText("");clearTutorAttachments();
        renderTutor(false);
    }

    private void chooseTutorAttachment() {
        JFileChooser chooser = new JFileChooser();
        chooser.setMultiSelectionEnabled(true);
        chooser.setFileFilter(new FileNameExtensionFilter("이미지 또는 PDF (PNG, JPEG, WebP, PDF)",
            "png", "jpg", "jpeg", "webp", "pdf"));
        chooser.setAcceptAllFileFilterUsed(false);
        if(chooser.showOpenDialog(this)!=JFileChooser.APPROVE_OPTION)return;
        try {
            File[] selected=chooser.getSelectedFiles();
            if(selected.length==0 && chooser.getSelectedFile()!=null)selected=new File[]{chooser.getSelectedFile()};
            for(File file:selected)addTutorAttachment(file.toPath(),false);
        } catch(Exception error) {showError(error.getMessage());}
    }

    private void installTutorPaste() {
        String action="synesisPasteTutorAttachment";
        question.getActionMap().put(action,new AbstractAction() {
            @Override public void actionPerformed(java.awt.event.ActionEvent event) {
                try {
                    Transferable clipboard=Toolkit.getDefaultToolkit().getSystemClipboard().getContents(null);
                    if(!pasteTutorTransferable(clipboard))question.paste();
                } catch(IllegalStateException error) {
                    showError("클립보드를 사용 중입니다. 잠시 후 다시 붙여넣어 주세요.");
                } catch(Exception error) {
                    showError("이미지를 붙여넣지 못했습니다: "+error.getMessage());
                }
            }
        });
        InputMap keys=question.getInputMap(JComponent.WHEN_FOCUSED);
        keys.put(KeyStroke.getKeyStroke(KeyEvent.VK_V,InputEvent.META_DOWN_MASK),action);
        keys.put(KeyStroke.getKeyStroke(KeyEvent.VK_V,InputEvent.CTRL_DOWN_MASK),action);
    }

    private boolean pasteTutorTransferable(Transferable clipboard) throws Exception {
        if(clipboard==null)return false;
        if(clipboard.isDataFlavorSupported(DataFlavor.javaFileListFlavor)) {
            Object files=clipboard.getTransferData(DataFlavor.javaFileListFlavor);
            if(files instanceof List<?> list && !list.isEmpty()) {
                List<Path> images=new ArrayList<>();
                for(Object item:list) {
                    if(!(item instanceof File file))return false;
                    Path selected=file.toPath();
                    String name=selected.getFileName().toString().toLowerCase(Locale.ROOT);
                    if(!(name.endsWith(".png") || name.endsWith(".jpg") || name.endsWith(".jpeg") || name.endsWith(".webp")))return false;
                    images.add(selected);
                }
                for(Path selected:images)addTutorAttachment(selected,false);
                question.requestFocusInWindow();
                return true;
            }
        }
        if(clipboard.isDataFlavorSupported(DataFlavor.imageFlavor)) {
            Image image=(Image)clipboard.getTransferData(DataFlavor.imageFlavor);
            ImageIcon loaded=new ImageIcon(image);
            int width=loaded.getIconWidth(),height=loaded.getIconHeight();
            if(width<1 || height<1 || (long)width*height>30_000_000L)
                throw new IllegalArgumentException("첨부 이미지가 너무 큽니다.");
            BufferedImage pixels=new BufferedImage(width,height,BufferedImage.TYPE_INT_ARGB);
            Graphics2D graphics=pixels.createGraphics();
            try {graphics.drawImage(loaded.getImage(),0,0,null);}finally {graphics.dispose();}
            Path saved=Files.createTempFile("synesis-tutor-paste-",".png");
            try {
                if(!ImageIO.write(pixels,"png",saved.toFile()) || Files.size(saved)>20_000_000L)
                    throw new IllegalArgumentException("첨부 이미지는 20MB 이하만 사용할 수 있습니다.");
                addTutorAttachment(saved,true);
                question.requestFocusInWindow();
                return true;
            } catch(Exception error) {Files.deleteIfExists(saved);throw error;}
        }
        return false;
    }

    private void addTutorAttachment(Path selected,boolean pasted) throws IOException {
        if(!Files.isRegularFile(selected) || Files.size(selected)>20_000_000L)
            throw new IllegalArgumentException("첨부 파일은 20MB 이하만 사용할 수 있습니다.");
        String name=selected.getFileName().toString().toLowerCase(Locale.ROOT);
        boolean pdf=name.endsWith(".pdf");
        if(!pdf && !(name.endsWith(".png") || name.endsWith(".jpg") || name.endsWith(".jpeg") || name.endsWith(".webp")))
            throw new IllegalArgumentException("이미지 또는 PDF만 첨부할 수 있습니다.");
        if(pdf && !tutorAttachments.isEmpty() || !pdf && tutorAttachments.stream().anyMatch(path->path.toString().toLowerCase(Locale.ROOT).endsWith(".pdf")))
            throw new IllegalArgumentException("PDF는 단독으로 첨부해 주세요.");
        if(tutorAttachments.contains(selected))return;
        TutorPreview preview=tutorPreview(selected,pasted?"붙여넣은 이미지":selected.getFileName().toString());
        tutorAttachments.add(selected);
        tutorAttachmentThumbnails.put(selected,preview);
        if(pasted)tutorPastedAttachments.add(selected);
        refreshTutorAttachments();
    }

    private static TutorPreview tutorPreview(Path path,String name) throws IOException {
        String lower=path.getFileName().toString().toLowerCase(Locale.ROOT);
        if(lower.endsWith(".pdf"))return new TutorPreview(name,null);
        BufferedImage image=ImageIO.read(path.toFile());
        if(image==null)throw new IllegalArgumentException("이미지를 읽을 수 없습니다.");
        int width=Math.max(1,Math.round(64f*image.getWidth()/Math.max(image.getWidth(),image.getHeight())));
        int height=Math.max(1,Math.round(64f*image.getHeight()/Math.max(image.getWidth(),image.getHeight())));
        BufferedImage small=new BufferedImage(width,height,BufferedImage.TYPE_INT_RGB);
        Graphics2D graphics=small.createGraphics();
        try {
            graphics.setColor(Color.WHITE);graphics.fillRect(0,0,width,height);
            graphics.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            graphics.drawImage(image,0,0,width,height,null);
        } finally {graphics.dispose();image.flush();}
        return new TutorPreview(name,new ImageIcon(small));
    }

    private void removeTutorAttachment(Path path) {
        tutorAttachments.remove(path);tutorAttachmentThumbnails.remove(path);
        if(tutorPastedAttachments.remove(path))try {Files.deleteIfExists(path);}catch(IOException ignored) {}
        refreshTutorAttachments();
    }

    private void clearTutorAttachments() {
        for(Path path:List.copyOf(tutorAttachments))removeTutorAttachment(path);
    }

    private void refreshTutorAttachments() {
        JPanel row=(JPanel)tutorAttachmentLabel.getClientProperty("synesis.attachmentRow");
        tutorAttachmentLabel.setText(tutorAttachments.isEmpty()?"":"첨부 "+tutorAttachments.size()+"개 · 순서대로 읽어요");
        tutorAttachmentPreviews.removeAll();
        for(int i=0;i<tutorAttachments.size();i++) {
            Path path=tutorAttachments.get(i);TutorPreview preview=tutorAttachmentThumbnails.get(path);
            JLayeredPane item=new JLayeredPane();
            item.setPreferredSize(new Dimension(72,72));
            JLabel thumbnail=new JLabel(preview.icon()==null?"PDF":null,preview.icon(),SwingConstants.CENTER);
            thumbnail.setBounds(2,2,68,68);
            thumbnail.setBorder(BorderFactory.createLineBorder(MistWorkspaceTheme.LINE));
            thumbnail.setToolTipText((i+1)+". "+preview.name());
            item.add(thumbnail,JLayeredPane.DEFAULT_LAYER);
            JButton remove=new JButton("×");
            remove.setBounds(52,0,20,20);
            remove.setMargin(new Insets(0,0,0,0));
            remove.setFont(new Font(UiFonts.FAMILY,Font.BOLD,13));
            remove.setBackground(StudyTheme.ACCENT_DARK);
            remove.setForeground(Color.WHITE);
            remove.setOpaque(true);
            remove.setFocusPainted(false);
            remove.setBorder(BorderFactory.createLineBorder(Color.WHITE));
            remove.setToolTipText("이 사진 제거");remove.addActionListener(event->removeTutorAttachment(path));
            item.add(remove,JLayeredPane.PALETTE_LAYER);tutorAttachmentPreviews.add(item);
        }
        if(row!=null)row.setVisible(!tutorAttachments.isEmpty());
        tutorAttachmentPreviews.revalidate();tutorAttachmentPreviews.repaint();
        if(tutorInputCard!=null)tutorInputCard.refresh();
    }

    private void askSelectedStudy(String selection) {
        askSelectedStudy(selection,new JsonObject());
    }
    private void askSelectedStudy(String selection,JsonObject context) {
        if(selection.isBlank())return;
        showTutor();
        askTutor("["+selection+"]\n\n이 부분에 대해 상세히 설명해줘.",context);
    }
    private void askTutor() {askTutor(null);}
    private void askTutor(String selectedQuestion) {askTutor(selectedQuestion,new JsonObject());}
    private void askTutor(String selectedQuestion,JsonObject selectionContext) {
        askTutor(selectedQuestion,selectionContext,page);
    }
    public boolean hasBackgroundQuizGeneration(){return quizGenerating||backgroundQuizzes.running();}
    private boolean quizDocumentVisible(String documentId) {
        return !closed&&source!=null&&source.id.equals(documentId);
    }
    private void runBackgroundQuiz(PdfSource target,JsonObject request,Consumer<JsonObject> finished,
                                   Consumer<JsonObject> liveEvent) {
        JsonObject snapshot=request.deepCopy();
        backgroundQuizzes.start(target.id,runner->{
            int ticket=runner.ticket();
            Files.deleteIfExists(target.folder.resolve("cancel"));
            Path path=target.folder.resolve("requests/"+UUID.randomUUID()+".json");
            Files.createDirectories(path.getParent());Files.writeString(path,JSON.toJson(snapshot),StandardCharsets.UTF_8);
            runner.run("pdf_ai.py",List.of("quiz","--folder",target.folder.toString(),"--request",path.toString(),
                "--allow-remote","--max-usd","1.0","--model","gpt-6-luna"),ticket,event->{
                if("quiz_stage".equals(str(event,"type")))SwingUtilities.invokeLater(()->{
                    if(backgroundQuizzes.publicationAllowed(target.id)&&quizDocumentVisible(target.id))liveEvent.accept(event);
                });
            });
            return readJson(path.resolveSibling(path.getFileName().toString().replace(".json",".result.json")));
        },(result,error)->SwingUtilities.invokeLater(()->{
            if(closed||!backgroundQuizzes.publicationAllowed(target.id))return;
            if(error==null)finished.accept(result);
            else if(quizDocumentVisible(target.id)) {
                quizGenerating=false;
                quiz.showGenerationFailure(error.getMessage()==null?"문제 출제를 완료하지 못했어요.":error.getMessage());
                setControls();
            }
        }));
    }
    private void startQuizGeneration(QuizPanel.GenerationRequest setup) {
        if(closed || source==null || index==null || busy || backgroundQuizzes.running(source.id)) {
            quiz.showGenerationFailure("PDF 준비나 진행 중인 작업이 끝난 뒤 출제해 주세요.");
            return;
        }
        long started=System.nanoTime();
        JsonObject request;
        try {
            request=QuizGenerationData.request(setup,conceptResultForDisplay(),summaryStrategyId(),source.id);
        } catch(IllegalArgumentException invalid) {
            quiz.showGenerationFailure(invalid.getMessage());
            return;
        }
        PdfSource quizSource=source;
        String documentId=quizSource.id;
        quizGenerating=true;
        quiz.setGenerating(true,"전체 개념 목차로 출제 범위를 배분하고 있어요.");
        runBackgroundQuiz(quizSource,request,result->{
            if(!quizDocumentVisible(documentId)) {
                if(result.has("questions")&&!result.getAsJsonArray("questions").isEmpty())
                    publishQuizWorkbook(quizSource,QuizWorkbook.fromResult(result),true);
                return;
            }
            try {
                if(!documentId.equals(str(result,"documentId")))throw new IllegalArgumentException("현재 PDF와 다른 문제집이에요.");
                if(result.has("questions")&&result.get("questions").isJsonArray()&&result.getAsJsonArray("questions").isEmpty()) {
                    quizGenerating=false;
                    QuizGenerationData.Result parsed=QuizGenerationData.parse(result,documentId);
                    quiz.showGenerationResult(parsed.questions(),Math.max(parsed.elapsedSeconds(),(System.nanoTime()-started)/1_000_000_000d),
                        parsed.totalUsd(),parsed.requestedCount(),parsed.note());
                    status.setText("문제집 생성 0/"+parsed.requestedCount()+"문제 · 기존 문제집 유지");
                } else {
                    JsonObject completed=result.deepCopy();
                    completed.addProperty("elapsedSeconds",Math.max(comparisonNumber(result,"elapsedSeconds"),(System.nanoTime()-started)/1_000_000_000d));
                    QuizWorkbook book=QuizWorkbook.fromResult(completed);
                    publishQuizWorkbook(quizSource,book,true);
                }
            } catch(IllegalArgumentException invalid) {
                quizGenerating=false;
                quiz.showGenerationFailure("생성 결과를 표시하지 못했어요. "+invalid.getMessage());
                status.setText("문제 결과 확인 필요 · 생성 기록은 보관됐어요.");
            }
            setControls();
        },event->{
            if("quiz_stage".equals(str(event,"type"))) {
                if(event.has("workbook")&&event.get("workbook").isJsonObject()) {
                    try {publishQuizWorkbook(quizSource,QuizWorkbook.fromResult(event.getAsJsonObject("workbook")),false);}
                    catch(IllegalArgumentException invalid) {
                        dev.synesis.poc.AppDiagnostics.error("quiz.live.snapshot",invalid,Map.of());
                    }
                }
                String message=str(event,"message");
                if(!message.isBlank()){
                    if(event.has("percent"))quiz.setGenerationProgress(event.get("percent").getAsInt(),message);
                    else quiz.setGenerating(true,message);
                    status.setText(message);
                }
            }
        });
    }
    private void publishQuizWorkbook(PdfSource target,QuizWorkbook book,boolean complete) {
        if(closed)return;
        List<QuizWorkbook> known=quizDocumentVisible(target.id)?quiz.workbooks():List.of();
        files.execute(()->{
            try {
                Optional<QuizWorkbook> named=QuizWorkbookStore.register(target.folder,book,known);
                SwingUtilities.invokeLater(()->{
                    if(!quizDocumentVisible(target.id))return;
                    if(complete) {
                        quizGenerating=false;
                        if(named.isPresent()) {
                            quiz.addWorkbook(named.get());
                            status.setText("문제집 생성 완료 · "+book.questions().size()+"/"+book.requestedCount()+"문제 · 목록에서 선택해 주세요.");
                        } else {quiz.setGenerating(false,"문제집 생성을 마쳤어요. 삭제한 문제집은 다시 표시하지 않아요.");status.setText("문제집 생성 종료");}
                        setControls();
                    } else named.ifPresent(quiz::acceptGenerationSnapshot);
                });
            } catch(Exception error) {
                SwingUtilities.invokeLater(()->{
                    if(!quizDocumentVisible(target.id))return;
                    if(complete){quizGenerating=false;quiz.showGenerationFailure("문제집 이름을 저장하지 못했어요. 생성 기록은 보관했어요.");setControls();}
                    status.setText("문제집 이름 저장 실패 · "+error.getMessage());
                });
            }
        });
    }
    private void renameQuizWorkbook(QuizWorkbook book,String requested) {
        PdfSource target=source;if(closed||target==null||!target.id.equals(book.documentId()))return;
        List<QuizWorkbook> known=quiz.workbooks();
        files.execute(()->{
            try {
                String name=QuizWorkbookStore.rename(target.folder,book,requested,known);
                SwingUtilities.invokeLater(()->{if(!closed&&source==target){quiz.renameWorkbook(book.id(),name);status.setText("문제집 이름을 변경했어요.");}});
            } catch(Exception error){workbookManagementFailure(target,"이름 변경",error);}
        });
    }
    private void deleteQuizWorkbook(QuizWorkbook book) {
        PdfSource target=source;if(closed||target==null||!target.id.equals(book.documentId()))return;
        files.execute(()->{
            try {
                QuizWorkbookStore.delete(target.folder,book);
                SwingUtilities.invokeLater(()->{if(!closed&&source==target){quizWorkbookOpenRevision++;quiz.removeWorkbook(book.id());status.setText("문제집을 삭제했어요.");}});
            } catch(Exception error){workbookManagementFailure(target,"삭제",error);}
        });
    }
    private void workbookManagementFailure(PdfSource target,String action,Exception error) {
        SwingUtilities.invokeLater(()->{if(!closed&&source==target){
            status.setText("문제집 "+action+" 실패");
            JOptionPane.showMessageDialog(this,error.getMessage(),"문제집 "+action,JOptionPane.ERROR_MESSAGE);
        }});
    }
    private void openQuizWorkbook(QuizWorkbook book) {
        PdfSource target=source;
        if(closed||target==null||!target.id.equals(book.documentId()))return;
        long revision=++quizWorkbookOpenRevision;
        files.execute(()->{
            try {
                Map<String,QuizWorkbook.Answer> answers=QuizWorkbookStore.loadAnswers(target.folder,book);
                SwingUtilities.invokeLater(()->{
                    if(closed||source!=target||revision!=quizWorkbookOpenRevision||!book.id().equals(quiz.requestedWorkbookId()))return;
                    quiz.openWorkbook(book,answers);
                });
            }catch(Exception error) {
                SwingUtilities.invokeLater(()->{
                    if(!closed&&source==target&&revision==quizWorkbookOpenRevision&&book.id().equals(quiz.requestedWorkbookId()))
                        status.setText("문제집 답변을 불러오지 못했어요. 목록에서 다시 선택해 주세요.");
                });
            }
        });
    }
    private void saveQuizWorkbookAnswers(QuizWorkbook book,Map<String,QuizWorkbook.Answer> answers) {
        PdfSource target=source;
        if(closed||target==null||!target.id.equals(book.documentId()))return;
        Map<String,QuizWorkbook.Answer> snapshot=Map.copyOf(answers);
        // Queue immutable snapshots in edit order. These writes must finish
        // even when the user switches PDFs before the worker reaches them.
        files.execute(()->{
            try {QuizWorkbookStore.saveAnswers(target.folder,book,snapshot);}
            catch(Exception error) {SwingUtilities.invokeLater(()->{
                if(!closed&&source==target&&book.id().equals(quiz.currentWorkbookId()))
                    status.setText("문제집 답변을 저장하지 못했어요.");
            });}
        });
    }
    private void openQuizConcept(QuizConceptLinks.Target target) {
        PdfSource current=source;
        if(closed||current==null||!current.id.equals(target.documentId()))return;
        if(QuizConceptLinks.find(target,conceptResultForDisplay())<0) {
            status.setText("개념 정리가 변경됐어요. 현재 개념 탭에서 내용을 확인해 주세요.");return;
        }
        showTab("개념정리");
        Runnable reveal=()->{
            if(closed||source!=current||!"개념정리".equals(selectedLearningTab))return;
            int index=QuizConceptLinks.find(target,conceptResultForDisplay());
            if(index<0)return;
            showConcepts(true);
            conceptOverview.revealConcept(index);
        };
        if(!LayoutMotionPanel.defer(conceptScroll,"quiz-concept-jump",reveal))reveal.run();
    }

    private void askQuizTutor(QuizTutorRequest quizRequest) {
        if(closed || source==null || index==null || busy || tutorBusy
            || !source.id.equals(quizRequest.question().documentId()))return;
        int evidencePage=quizRequest.preferredPage();
        int requestPage=evidencePage>0&&evidencePage<=source.count?evidencePage:page;
        showTutor();
        askTutor(quizRequest.prompt(),new JsonObject(),requestPage);
    }
    private void askTutor(String selectedQuestion,JsonObject selectionContext,int requestPage) {
        askTutor(selectedQuestion,selectionContext,requestPage,null);
    }
    private void askTutor(String selectedQuestion,JsonObject selectionContext,int requestPage,TutorStarterPrompt starter) {
        boolean fromSelection=selectedQuestion!=null;
        if(index==null || tutorBusy || !fromSelection && question.getText().isBlank() && tutorAttachments.isEmpty()) return;
        List<Path> attachments=fromSelection?List.of():List.copyOf(tutorAttachments);
        List<Path> transientAttachments=attachments.stream().filter(tutorPastedAttachments::contains).toList();
        List<TutorPreview> previews=attachments.stream().map(tutorAttachmentThumbnails::get).toList();
        tutorPastedAttachments.removeAll(transientAttachments);
        String text=fromSelection?selectedQuestion:question.getText().isBlank()?"첨부한 자료를 설명해줘":question.getText().strip();
        boolean localGreeting=attachments.isEmpty() && isTutorGreeting(text);
        CloudChoice choice=localGreeting?null:new CloudChoice("gpt-6-luna",.13,true);
        JsonObject request=new JsonObject();request.addProperty("question",text);request.addProperty("page",requestPage);request.add("memory",tutorMemory.deepCopy());
        if(starter!=null)starter.addTo(request);
        if(fromSelection&&!selectionContext.isEmpty())request.add("selectionContext",selectionContext.deepCopy());
        addTutorAnswerOptions(request);
        request.addProperty("strategy",summaryStrategyId());
        request.addProperty("webFallback",choice!=null && choice.webFallback());
        if(!attachments.isEmpty()) {
            JsonArray sources=new JsonArray();
            for(Path attachment:attachments)sources.add(attachment.toString());
            request.add("attachmentSources",sources);
        }
        String answerMarker="SYNESISTUTORANSWER"+UUID.randomUUID().toString().replace("-","")+"END";
        conversation.add(new TutorTurn(text,answerMarker,previews,fromSelection&&starter==null));
        saveTutorConversation();
        activeTutorMarker=answerMarker;clearTutorStream();lastTutorStreamPaint=0;
        tutorActivity.start(answerMarker);
        if(!fromSelection){question.setText("");clearTutorAttachments();}
        renderTutor(false);
        long started=System.nanoTime();
        runAi("tutor",request,choice,result->{
            if(!answerMarker.equals(activeTutorMarker))return;
            rememberTutorAnswer(answerMarker,result);
            activeTutorMarker=null;clearTutorStream();
            saveTutorConversation();renderTutor(true);
            if(!busy)status.setText((localGreeting?"AI멘토 인사 완료":"AI멘토 답변 완료")+" · "+formatElapsed(System.nanoTime()-started));
        },event->acceptTutorEvent(answerMarker,event),transientAttachments);
    }

    private void addTutorAnswerOptions(JsonObject request){
        request.addProperty("mode",tutorMode.getSelectedIndex()==1?"deep":"quick");
        request.addProperty("reasoningEffort",tutorReasoning.getSelectedIndex()==1?"low":"medium");
    }

    private void acceptTutorEvent(String marker,JsonObject event) {
        if(!marker.equals(activeTutorMarker))return;
        if(str(event,"type").equals("tutor_stage")) {
            if(str(event,"stage").equals("answer_wait"))tutorActivity.pdfSearchDone(marker);
            return;
        }
        if(!str(event,"type").equals("tutor_delta"))return;
        tutorActivity.answerStarted(marker);
        tutorTextReveal.accept(str(event,"text"));
        if(LayoutMotionPanel.defer(tutorScroll,"tutor-delta",()->{
            if(marker.equals(activeTutorMarker))acceptTutorEvent(marker,event);
        }))return;
        if(!tutorFadeTimer.isRunning())tutorFadeTimer.start();
    }

    private void completeTutorStream(JsonObject result,Runnable complete) {
        JsonObject event=new JsonObject();event.addProperty("type","tutor_delta");
        event.addProperty("text",str(result,"answer"));
        acceptTutorEvent(activeTutorMarker,event);
        tutorStreamCompletion=complete;
        if(tutorPanel.isDisplayable()&&!dev.synesis.poc.ui.AnimationWindow.active(tutorPanel)){
            tutorStreamCompletion=null;complete.run();
        }else if(!tutorFadeTimer.isRunning())tutorFadeTimer.start();
    }

    private void syncTutorAnimations(){
        boolean visible=dev.synesis.poc.ui.AnimationWindow.active(tutorPanel);
        if(visible){
            if(activeTutorMarker!=null){tutorFadeTimer.start();tutorThinkingTimer.start();}
            if(tutorBubbles.values().stream().anyMatch(bubble->bubble.lastResizeNanos!=0))tutorResizeTimer.start();
            if(!tutorTimeLabels.isEmpty()){refreshTutorTimes();tutorTimeTimer.start();}
        }else{
            tutorFadeTimer.stop();tutorThinkingTimer.stop();tutorTimeTimer.stop();tutorResizeTimer.stop();
            if(tutorStreamCompletion!=null){Runnable done=tutorStreamCompletion;tutorStreamCompletion=null;done.run();}
        }
    }

    private void refreshTutorActivity() {
        if(streamingTutorBubble==null)return;
        streamingTutorBubble.thinkingLabel.setText(tutorActivity.text());
        streamingTutorBubble.doLayout();streamingTutorBubble.repaint();
    }

    private record CloudChoice(String model,double budget,boolean webFallback) {}
    static String tutorAnswerHtml(JsonObject result) {return tutorAnswerHtml(result,StudyFontSettings.TUTOR_DEFAULT);}
    static String tutorAnswerHtml(JsonObject result,int fontSize) {
        return tutorAnswerHtml(result,fontSize,800);
    }
    private static String tutorAnswerHtml(JsonObject result,int fontSize,int width) {
        String html=StudyMarkdown.renderWithScrollableMath(str(result,"answer"),fontSize,false,width);
        if(str(result,"kind").equals("web_generated") && result.has("webSources"))
            for(JsonElement item:result.getAsJsonArray("webSources")) {
                JsonObject web=item.getAsJsonObject();String marker="["+web.get("number").getAsInt()+"]";
                html=StudyMarkdown.linkProseReference(html,marker,str(web,"url"));
            }
        return html;
    }
    private void renderTutor(boolean preserveScroll) {
        if(LayoutMotionPanel.defer(tutorScroll,"tutor",()->renderTutor(preserveScroll)))return;
        tutorReflowQueue.clear();tutorViewportResizeTimer.stop();
        TutorScrollKeeper.Position scrollPosition=tutorScrollKeeper.capture(!preserveScroll);
        tutorAnswers.keySet().removeIf(marker->conversation.stream().noneMatch(turn->turn.marker.equals(marker)));
        tutorBubbles.keySet().removeIf(marker->conversation.stream().noneMatch(turn->turn.marker.equals(marker)));
        tutorMessages.removeAll();
        tutorTimeLabels.clear();tutorFollowUps.clear();
        streamingTutorBubble=null;
        int maxWidth=tutorBubbleWidth();
        int fontSize=tutorFontSize.getValue();
        for(TutorTurn turn:conversation) {
            int naturalUserWidth=Math.max(110,(int)Math.round(maxWidth*.81));
            if(!turn.previews.isEmpty())naturalUserWidth=Math.max(naturalUserWidth,200);
            int userWidth=Math.min(maxWidth,naturalUserWidth);
            String userContent=turn.studySelection
                ?StudyMarkdown.renderWithScrollableMath(turn.question,fontSize,false,Math.max(80,userWidth-24))
                :"<p>"+escape(turn.question).replace("\n","<br>")+"</p>";
            RoundedTutorBubble userBubble=addTutorBubble(userContent,true,userWidth,fontSize,turn.previews);
            ((JComponent)userBubble.getParent()).putClientProperty(TutorScrollKeeper.ANCHOR,turn.marker+"/question");
            userBubble.putClientProperty("synesis.userWidthLimit",Integer.MAX_VALUE);
            addTutorUserCopy(turn,userBubble);
            JsonObject result=tutorAnswers.get(turn.marker);
            String answer=result!=null?tutorAnswerHtml(result,fontSize,maxWidth-32)+tutorSourcesHtml(turn.marker,result):
                turn.failure!=null?"<p>"+escape(turn.failure)+"</p>":
                turn.marker.equals(activeTutorMarker)?streamingTutorContent(fontSize):"";
            if(!answer.isBlank()) {
                JPanel identity=new JPanel(new BorderLayout(8,0));identity.setOpaque(false);identity.setAlignmentX(Component.LEFT_ALIGNMENT);
                JLabel name=MistWorkspaceTheme.label("AI멘토",12,MistWorkspaceTheme.INK,Font.PLAIN);name.setIcon(MistWorkspaceTheme.icon("spark",16));name.setIconTextGap(8);identity.add(name,BorderLayout.WEST);
                String grounded=turn.marker.equals(activeTutorMarker)?"답변 작성 중":result!=null&&result.has("evidence")&&result.get("evidence").isJsonArray()&&!result.getAsJsonArray("evidence").isEmpty()?"원문을 바탕으로 답변":"학습 설명";
                identity.add(MistWorkspaceTheme.label(grounded,10,MistWorkspaceTheme.MUTED,Font.PLAIN),BorderLayout.EAST);
                identity.putClientProperty(TutorScrollKeeper.ANCHOR,turn.marker+"/identity");
                identity.setMaximumSize(new Dimension(Integer.MAX_VALUE,28));identity.setPreferredSize(new Dimension(maxWidth,28));tutorMessages.add(identity);tutorMessages.add(Box.createVerticalStrut(12));
                String content=answer;
                RoundedTutorBubble bubble=tutorBubbles.get(turn.marker);
                if(bubble==null) {
                    bubble=new RoundedTutorBubble(content,false,maxWidth,fontSize,this::navigate,List.of());
                    tutorBubbles.put(turn.marker,bubble);
                } else {
                    bubble.updateContent(content,maxWidth,fontSize);
                    if(bubble.lastResizeNanos!=0 && !tutorResizeTimer.isRunning())tutorResizeTimer.start();
                }
                if(turn.marker.equals(activeTutorMarker))bubble.thinkingLabel.setText(tutorActivity.text());
                bubble.setThinking(turn.marker.equals(activeTutorMarker),
                    turn.marker.equals(activeTutorMarker) && streamingTutorText.isBlank());
                if(bubble.lastResizeNanos!=0 && !tutorResizeTimer.isRunning())tutorResizeTimer.start();
                bubble.putClientProperty("synesis.tutorMarker",turn.marker);
                addTutorBubbleRow(bubble,false);
                ((JComponent)bubble.getParent()).putClientProperty(TutorScrollKeeper.ANCHOR,turn.marker+"/answer");
                if(result!=null)addTutorFeedback(turn,result,maxWidth);
                if(turn.marker.equals(activeTutorMarker))streamingTutorBubble=bubble;
            }
        }
        tutorMessages.revalidate();tutorMessages.repaint();
        tutorCards.show(tutorBody,conversation.isEmpty()?"empty":"conversation");
        if(activeTutorMarker!=null && !tutorFadeTimer.isRunning())tutorFadeTimer.start();
        if(!tutorTimeLabels.isEmpty()&&!tutorTimeTimer.isRunning())tutorTimeTimer.start();
        if(tutorTimeLabels.isEmpty())tutorTimeTimer.stop();
        tutorScrollKeeper.restore(scrollPosition);
    }

    private void addTutorFeedback(TutorTurn turn,JsonObject result,int width){
        JPanel feedback=new JPanel(new BorderLayout());feedback.setOpaque(false);feedback.setAlignmentX(Component.LEFT_ALIGNMENT);
        feedback.putClientProperty(TutorScrollKeeper.ANCHOR,turn.marker+"/feedback");
        JPanel actions=new JPanel(new FlowLayout(FlowLayout.LEFT,0,0));actions.setOpaque(false);
        JButton copy=new MessageCopyButton("답변 복사",MistWorkspaceTheme.MUTED,()->str(result,"answer"),text->status.setText(text));
        JToggleButton like=new JToggleButton(MistWorkspaceTheme.icon("like",14));MistWorkspaceTheme.button(like,false);like.setBorder(new EmptyBorder(0,0,0,0));like.setPreferredSize(new Dimension(24,24));like.setToolTipText("좋아요 · 이 대화에서만 표시돼요");like.setSelected(likedTutorAnswers.contains(turn.marker));
        like.getAccessibleContext().setAccessibleName("답변 좋아요");
        like.addActionListener(e->{if(like.isSelected())likedTutorAnswers.add(turn.marker);else likedTutorAnswers.remove(turn.marker);});
        actions.add(copy);
        JLabel credits=MistWorkspaceTheme.label(tutorCreditLabel(result),10,MistWorkspaceTheme.MUTED,Font.PLAIN);
        credits.setBorder(new EmptyBorder(0,8,0,0));
        credits.setToolTipText("<html>"+tutorCostHtml(result)+"</html>");
        actions.add(credits);actions.add(like);feedback.add(actions,BorderLayout.WEST);
        if(turn.answeredAt==0)turn.answeredAt=System.currentTimeMillis();
        JLabel time=MistWorkspaceTheme.label(TutorPresentation.timeLabel(turn.answeredAt,System.currentTimeMillis()),10,MistWorkspaceTheme.MUTED,Font.PLAIN);
        time.setToolTipText("<html>"+tutorCostHtml(result)+"</html>");tutorTimeLabels.put(turn.marker,time);feedback.add(time,BorderLayout.EAST);
        feedback.setPreferredSize(new Dimension(width,24));feedback.setMaximumSize(new Dimension(Integer.MAX_VALUE,24));tutorMessages.add(feedback);tutorMessages.add(Box.createVerticalStrut(12));
        String followUp=TutorPresentation.followUp(result);
        if(!followUp.isEmpty()){
            JButton suggestion=new TutorFollowUpButton(followUp,width);
            suggestion.putClientProperty(TutorScrollKeeper.ANCHOR,turn.marker+"/suggestion");
            suggestion.setEnabled(index!=null&&!tutorBusy);suggestion.addActionListener(e->{question.setText(followUp);askTutor();});tutorFollowUps.add(suggestion);tutorMessages.add(suggestion);tutorMessages.add(Box.createVerticalStrut(16));
        }
    }

    private void refreshTutorTimes(){
        long now=System.currentTimeMillis();for(TutorTurn turn:conversation){JLabel label=tutorTimeLabels.get(turn.marker);if(label!=null)label.setText(TutorPresentation.timeLabel(turn.answeredAt,now));}
    }

    private void addTutorUserCopy(TutorTurn turn,RoundedTutorBubble bubble) {
        tutorMessages.remove(tutorMessages.getComponentCount()-1); // Replace the bubble's trailing gap with its footer.
        tutorMessages.add(Box.createVerticalStrut(4));
        JPanel footer=new JPanel(new FlowLayout(FlowLayout.RIGHT,0,0));footer.setOpaque(false);
        JPanel row=new JPanel(new FlowLayout(FlowLayout.RIGHT,0,0)){
            @Override public void doLayout(){footer.setPreferredSize(new Dimension(bubble.getPreferredSize().width,24));super.doLayout();}
        };row.setOpaque(false);row.setAlignmentX(Component.LEFT_ALIGNMENT);
        footer.add(new MessageCopyButton("메시지 복사",MistWorkspaceTheme.MUTED,()->turn.question,text->status.setText(text),.8f));
        row.add(footer);row.setMaximumSize(new Dimension(Integer.MAX_VALUE,24));row.setPreferredSize(new Dimension(bubble.getPreferredSize().width,24));
        row.putClientProperty(TutorScrollKeeper.ANCHOR,turn.marker+"/question-copy");
        tutorMessages.add(row);tutorMessages.add(Box.createVerticalStrut(14));
    }
    private void scheduleTutorReflow() {
        int width=tutorBubbleWidth();
        for(JButton suggestion:tutorFollowUps)
            if(suggestion instanceof TutorFollowUpButton wrapped)wrapped.reflowWidth(width);
        tutorReflowQueue.clear();
        Rectangle visible=tutorMessages.getVisibleRect();
        List<RoundedTutorBubble> offscreen=new ArrayList<>();
        for(Component component:tutorMessages.getComponents())
            if(component instanceof JPanel row && row.getComponentCount()>0
                && row.getComponent(0) instanceof RoundedTutorBubble bubble) {
                if(row.getBounds().intersects(visible))tutorReflowQueue.addLast(bubble);
                else offscreen.add(bubble);
            }
        tutorReflowQueue.addAll(offscreen);
        if(!tutorReflowQueue.isEmpty() && !tutorViewportResizeTimer.isRunning())tutorViewportResizeTimer.start();
    }
    private void reflowNextTutorBubble() {
        if(closed || tutorReflowQueue.isEmpty()) {tutorViewportResizeTimer.stop();return;}
        RoundedTutorBubble bubble=tutorReflowQueue.removeFirst();
        if(!(bubble.getParent() instanceof JPanel row) || row.getParent()!=tutorMessages)return;
        TutorScrollKeeper.Position scrollPosition=tutorScrollKeeper.capture(false);
        int width=tutorBubbleWidth(),fontSize=tutorFontSize.getValue();
        if(bubble.getClientProperty("synesis.userWidthLimit") instanceof Integer naturalWidth)
            width=Math.min((int)Math.round(width*.81),naturalWidth);
        else if(bubble.getClientProperty("synesis.tutorMarker") instanceof String marker) {
            JsonObject result=tutorAnswers.get(marker);
            if(result!=null) {
                String content=tutorAnswerHtml(result,fontSize,width-32)+tutorSourcesHtml(marker,result);
                bubble.updateContent(content,width,fontSize);
            }
        }
        bubble.reflowWidth(width);
        sizeTutorBubbleRow(row,bubble);
        tutorMessages.revalidate();tutorMessages.repaint();
        tutorScrollKeeper.restore(scrollPosition);
        if(tutorReflowQueue.isEmpty())tutorViewportResizeTimer.stop();
    }
    private String streamingTutorContent(int fontSize) {
        if(streamingTutorText.isBlank())return "<p></p>";
        int width=tutorContentWidth();
        if(streamingTutorFontSize!=fontSize || streamingTutorMathWidth!=width) {
            streamingTutorFontSize=fontSize;
            streamingTutorMathWidth=width;
            streamingTutorHtml=StudyMarkdown.renderWithScrollableMath(streamingTutorText,fontSize,false,width);
        }
        return tutorStreamFade.decorate(streamingTutorHtml,System.currentTimeMillis());
    }
    private int tutorContentWidth() {
        return tutorBubbleWidth()-32;
    }
    private int tutorBubbleWidth() {
        int width=tutorScroll.getViewport().getWidth();
        Insets padding=tutorMessages.getInsets();
        return Math.max(104,(width>0?width:320)-padding.left-padding.right);
    }
    private void refreshTutorFade() {
        if(activeTutorMarker==null || streamingTutorBubble==null) {tutorFadeTimer.stop();return;}
        if(LayoutMotionPanel.defer(tutorScroll,"tutor-fade",()->{
            if(activeTutorMarker!=null){refreshTutorFade();tutorFadeTimer.start();}
        })) {tutorFadeTimer.stop();return;}
        if(tutorScroll.isDisplayable()&&!dev.synesis.poc.ui.AnimationWindow.active(tutorPanel)) {
            tutorFadeTimer.stop();tutorThinkingTimer.stop();
            if(tutorStreamCompletion!=null){Runnable done=tutorStreamCompletion;tutorStreamCompletion=null;done.run();}
            return;
        }
        String revealed=tutorTextReveal.advance();
        if(!revealed.equals(streamingTutorText)) {
            streamingTutorText=revealed;
            streamingTutorFontSize=tutorFontSize.getValue();
            streamingTutorMathWidth=tutorContentWidth();
            streamingTutorHtml=StudyMarkdown.renderWithScrollableMath(streamingTutorText,streamingTutorFontSize,false,streamingTutorMathWidth);
            tutorStreamFade.accept(streamingTutorHtml,System.currentTimeMillis());
        }
        TutorScrollKeeper.Position scrollPosition=tutorScrollKeeper.capture(false);
        int fontSize=tutorFontSize.getValue();
        RoundedTutorBubble bubble=streamingTutorBubble;
        if(dev.synesis.poc.ui.AnimationWindow.active(tutorPanel)&&!tutorThinkingTimer.isRunning())tutorThinkingTimer.start();
        bubble.updateContent(streamingTutorContent(fontSize),
            tutorBubbleWidth(),fontSize);
        bubble.setThinking(true,streamingTutorText.isBlank());
        if(bubble.lastResizeNanos!=0 && !tutorResizeTimer.isRunning())tutorResizeTimer.start();
        tutorScrollKeeper.restore(scrollPosition);
        if(tutorStreamCompletion!=null&&tutorTextReveal.complete()&&!tutorStreamFade.active(System.currentTimeMillis())) {
            Runnable done=tutorStreamCompletion;tutorStreamCompletion=null;done.run();
        }
        // Waiting for the next token only animates the small thinking label, never the HTML body.
        if(tutorTextReveal.complete()&&!tutorStreamFade.active(System.currentTimeMillis()))tutorFadeTimer.stop();
    }
    private void animateTutorBubbles() {
        if(LayoutMotionPanel.defer(tutorScroll,"tutor-bubble-motion",()->{
            if(!closed){animateTutorBubbles();}
        })) {tutorResizeTimer.stop();return;}
        TutorScrollKeeper.Position scrollPosition=tutorScrollKeeper.capture(false);
        boolean moving=false,changed=false;
        long now=System.nanoTime();
        for(RoundedTutorBubble bubble:tutorBubbles.values()) {
            if(bubble.lastResizeNanos==0)continue;
            Dimension before=bubble.getPreferredSize();
            moving|=bubble.animateSize(now);
            if(!before.equals(bubble.getPreferredSize()) && bubble.getParent() instanceof JPanel row) {
                sizeTutorBubbleRow(row,bubble);
                changed=true;
            }
        }
        if(changed) {
            tutorMessages.revalidate();tutorMessages.repaint();
            tutorScrollKeeper.restore(scrollPosition);
        }
        if(!moving)tutorResizeTimer.stop();
    }
    private void clearTutorStream() {
        tutorThinkingTimer.stop();
        tutorTextReveal.reset();tutorStreamCompletion=null;
        tutorActivity.clear();
        tutorFadeTimer.stop();tutorStreamFade.reset();streamingTutorText="";streamingTutorHtml="";
        streamingTutorBubble=null;streamingTutorFontSize=0;
    }
    private static boolean isTutorGreeting(String question) {
        String text=java.text.Normalizer.normalize(question,java.text.Normalizer.Form.NFC)
            .strip().toLowerCase(Locale.ROOT);
        return text.matches("(?:ㅎㅇ+|하이+|hi+|hello|안녕(?:하세요|하십니까)?|반가워(?:요)?|"
            +"(?:너|넌|너는|당신은)\\s*누구(?:야|예요|세요)?|자기소개\\s*해\\s*줘(?:요)?)[\\s!?~.…]*");
    }
    private RoundedTutorBubble addTutorBubble(String content,boolean user,int width,int fontSize) {
        return addTutorBubble(content,user,width,fontSize,List.of());
    }
    private RoundedTutorBubble addTutorBubble(String content,boolean user,int width,int fontSize,
                                             List<TutorPreview> previews) {
        RoundedTutorBubble bubble=new RoundedTutorBubble(content,
            user,width,fontSize,this::navigate,previews);
        addTutorBubbleRow(bubble,user);
        return bubble;
    }
    private void addTutorBubbleRow(RoundedTutorBubble bubble,boolean user) {
        JPanel row=new JPanel(new FlowLayout(user?FlowLayout.RIGHT:FlowLayout.LEFT,0,0));
        row.setOpaque(false);row.setAlignmentX(Component.LEFT_ALIGNMENT);
        row.add(bubble);sizeTutorBubbleRow(row,bubble);
        tutorMessages.add(row);tutorMessages.add(Box.createVerticalStrut(14));
    }
    private static void sizeTutorBubbleRow(JPanel row,RoundedTutorBubble bubble) {
        int height=bubble.getPreferredSize().height;
        row.setMinimumSize(new Dimension(0,height));
        row.setPreferredSize(new Dimension(bubble.getPreferredSize().width,height));
        row.setMaximumSize(new Dimension(Integer.MAX_VALUE,height));
        row.invalidate();
    }
    private static String tutorDocumentHtml(String body,int fontSize) {
        return SummarySkin.formulaDocument(body,fontSize).replace("</style>",
            "a{color:#61656c;}p{margin-top:0;margin-bottom:12px;}"
            +".tutor-name{color:#141414;font-size:11pt;font-weight:bold;margin-bottom:10px;}"
            +".tutor-cost{color:#61656c;font-size:10pt;margin-top:14px;}</style>");
    }
    private static String tutorUserDocumentHtml(String body,int fontSize) {
        return documentHtml("",body,fontSize).replace("margin:14px 22px;","margin:0;font-weight:normal;")
            .replace("p{margin-top:5px;margin-bottom:12px;}","p{margin-top:0;margin-bottom:12px;}")
            .replace("color:#182234;","color:#45474c;").replace("background:#fafaf8;","background:"+MistWorkspaceTheme.SOFT_HEX+";").replace("</style>",
            "body,p,li{color:#45474c;}h1,h2,h3,h4{color:#141414;}a{color:#61656c;}"
            +"code{color:#45474c;background:"+StudyCodeBlock.INLINE_BACKGROUND+";}pre,pre code{color:#45474c;background:"+StudyCodeBlock.BACKGROUND+";}blockquote,th{color:#45474c;background:"+MistWorkspaceTheme.SOFT_HEX+";}"
            +".muted{color:#61656c;}.tutor-name{color:#141414;font-size:11pt;font-weight:bold;margin-bottom:10px;}"
            +".tutor-cost{color:#61656c;font-size:10pt;margin-top:14px;}"
            +"</style>");
    }
    static String tutorCostHtml(JsonObject result) {
        if(!result.has("runUsage") || !result.get("runUsage").isJsonObject())
            return "greeting".equals(str(result,"kind"))
                ?"<p class='tutor-cost'>이번 답변 비용: $0.00000000 · 약 0.00원 · "+tutorCreditsHtml(0)+"</p>"
                :"<p class='tutor-cost'>이번 답변 비용·크레딧: 사용량 확인 필요</p>";
        JsonObject report=result.getAsJsonObject("runUsage");
        if(!report.has("usageBasedUsd") || report.get("usageBasedUsd").isJsonNull())
            return "<p class='tutor-cost'>이번 답변 비용·크레딧: 사용량 확인 필요</p>";
        double usd=report.has("usageBasedUsd")?report.get("usageBasedUsd").getAsDouble():0;
        String label="이번 답변 비용";
        String tail="";
        if(report.has("inputTokens") && report.has("outputTokens"))
            tail+=" · "+String.format(Locale.KOREA,"%,d",report.get("inputTokens").getAsLong()
                +report.get("outputTokens").getAsLong())+"토큰";
        return "<p class='tutor-cost'>"+label+": "+String.format(Locale.ROOT,"$%.8f · 약 %.2f원",usd,usd*1400)
            +" · "+tutorCreditsHtml(usd)+tail+"</p>";
    }
    private static String tutorCreditLabel(JsonObject result) {
        if(!result.has("runUsage") || !result.get("runUsage").isJsonObject())
            return "greeting".equals(str(result,"kind"))?"0.00 크레딧":"크레딧 확인 중";
        JsonObject usage=result.getAsJsonObject("runUsage");
        if(!usage.has("usageBasedUsd") || usage.get("usageBasedUsd").isJsonNull())return "크레딧 확인 중";
        return CreditWallet.display(CreditWallet.credits(usage.get("usageBasedUsd").getAsDouble()))+" 크레딧";
    }
    private static String tutorCreditsHtml(double usd) {
        String formatted=CreditWallet.display(CreditWallet.credits(usd));
        int decimal=formatted.lastIndexOf('.');
        return formatted.substring(0,decimal)+"<span style='font-size:7pt'>"+formatted.substring(decimal)
            +"</span> 크레딧";
    }
    private String tutorSourcesHtml(String marker,JsonObject result) {
        JsonArray evidence=result.has("evidence") && result.get("evidence").isJsonArray()?result.getAsJsonArray("evidence"):new JsonArray();
        JsonArray related=result.has("relatedPages") && result.get("relatedPages").isJsonArray()?result.getAsJsonArray("relatedPages"):new JsonArray();
        JsonArray visual=result.has("visualPages") && result.get("visualPages").isJsonArray()?result.getAsJsonArray("visualPages"):new JsonArray();
        JsonArray web=result.has("webSources") && result.get("webSources").isJsonArray()?result.getAsJsonArray("webSources"):new JsonArray();
        if(evidence.isEmpty() && related.isEmpty() && visual.isEmpty() && web.isEmpty())return "";
        boolean open=expandedTutorEvidence.contains(marker);
        String label=!evidence.isEmpty()?"PDF 내 근거":!web.isEmpty()?"외부 웹 출처":"관련 PDF 페이지";
        StringBuilder html=new StringBuilder("<p class='muted'><a href='tutor-evidence:").append(marker).append("'>")
            .append(label).append(open?" 닫기":" 보기").append("</a></p>");
        if(!open)return html.toString();
        for(JsonElement item:evidence) {
            JsonObject quote=item.getAsJsonObject();
            html.append("<blockquote>").append(escape(str(quote,"quote"))).append("<br>")
                .append(pageLink(quote.get("page").getAsInt())).append("</blockquote>");
        }
        if(!visual.isEmpty()) {
            html.append("<p class='muted'>이미지 해석 참고: ");
            for(JsonElement item:visual)html.append(pageLink(item.getAsInt())).append(" ");
            html.append("</p>");
        }
        if(!related.isEmpty()) {
            html.append("<p class='muted'>함께 확인할 페이지: ");
            for(JsonElement item:related)html.append(pageLink(item.getAsInt())).append(" ");
            html.append("</p>");
        }
        for(JsonElement item:web) {
            JsonObject source=item.getAsJsonObject();
            html.append("<p><a href='").append(escape(str(source,"url"))).append("'>")
                .append(escape(str(source,"title"))).append("</a></p>");
        }
        return html.toString();
    }
    private void runAi(String command,JsonObject request,CloudChoice choice,Consumer<JsonObject> finished) {
        runAi(command,request,choice,finished,null);
    }
    private void runAi(String command,JsonObject request,CloudChoice choice,Consumer<JsonObject> finished,
                       Consumer<JsonObject> liveEvent) {
        runAi(command,request,choice,finished,liveEvent,List.of());
    }
    private void runAi(String command,JsonObject request,CloudChoice choice,Consumer<JsonObject> finished,
                       Consumer<JsonObject> liveEvent,List<Path> transientAttachments) {
        long started=System.nanoTime();
        boolean tutorCommand=command.equals("tutor");
        PdfSource target=source;
        int epoch=tutorCommand?tutorGeneration.get():generation.get();
        PdfProcess runner=tutorCommand?tutorProcesses:processes;
        int ticket=runner.ticket();
        Consumer<Runnable> deliver=action->{if(tutorCommand)onTutorEdt(epoch,action);else onEdt(epoch,action);};
        ChatReplyControl reply=tutorCommand?new ChatReplyControl():null;
        if(tutorCommand){tutorReply=reply;setTutorBusy(true);}
        else setBusy(true,command.equals("vision-plan")?"생성 계획과 예상 사용량을 계산하고 있어요."
            :choice==null?"PDF 근거 검색 중…":"AI 분석 중…");
        (tutorCommand?tutorJobs:jobs).execute(()->{
            Path attachmentDirectory=null;
            try {
                if(closed || (tutorCommand?epoch!=tutorGeneration.get():epoch!=generation.get())) return;
                if(!tutorCommand)Files.deleteIfExists(target.folder.resolve("cancel"));
                Path requestFile=target.folder.resolve("requests/"+UUID.randomUUID()+".json");Files.createDirectories(requestFile.getParent());
                JsonObject wireRequest=request.deepCopy();
                if(command.equals("tutor") && wireRequest.has("attachmentSources")) {
                    attachmentDirectory=target.folder.resolve("requests/attachments/"+UUID.randomUUID());
                    Files.createDirectories(attachmentDirectory);
                    JsonArray copied=new JsonArray();int order=0;
                    for(JsonElement sourcePath:wireRequest.getAsJsonArray("attachmentSources")) {
                        Path selected=Path.of(sourcePath.getAsString());
                        Path copy=attachmentDirectory.resolve(String.format(Locale.ROOT,"%03d-%s",++order,selected.getFileName()));
                        Files.copy(selected,copy);
                        copied.add(target.folder.relativize(copy).toString());
                    }
                    wireRequest.remove("attachmentSources");
                    wireRequest.add("attachmentPaths",copied);
                }
                Files.writeString(requestFile,JSON.toJson(wireRequest),StandardCharsets.UTF_8);
                List<String> args=new ArrayList<>(List.of(command,"--folder",target.folder.toString(),"--request",requestFile.toString()));
                if(choice!=null)args.addAll(List.of("--allow-remote","--max-usd",Double.toString(choice.budget),"--model",choice.model));
                try {
                    runner.run("pdf_ai.py",args,ticket,event->{
                        if(liveEvent!=null && (str(event,"type").equals("tutor_delta") || str(event,"type").equals("tutor_stage")
                                || command.equals("quiz") && str(event,"type").equals("quiz_stage")))deliver.accept(()->liveEvent.accept(event));
                        else if(!tutorCommand)handleProgress(epoch,event);
                    },null,reply);
                } catch (PdfProcess.UnreportedFailure failure) {
                    if (!command.equals("vision-plan") || closed || epoch!=generation.get()) throw failure;
                    // The cost plan is local and idempotent. Retry one silent worker exit only.
                    runner.run("pdf_ai.py",args,ticket,event->handleProgress(epoch,event));
                }
                Path resultFile=requestFile.resolveSibling(requestFile.getFileName().toString().replace(".json",".result.json"));
                JsonObject result=readJson(resultFile);
                if(command.equals("generate")) {
                    // Backfill and persist small cost summaries on the worker,
                    // never scan historical JSON on the Swing event thread.
                    try {result.add("pageCostComparison",PdfGenerationCostStats.recordAndCompare(pdfStorageRoot,result,wireRequest));}
                    catch(Exception unavailable) {JsonObject note=new JsonObject();note.addProperty("historyUnavailable",true);result.add("pageCostComparison",note);}
                }
                JsonObject refreshedDocument=null;
                if(command.equals("generate"))try {refreshedDocument=readJson(target.folder.resolve("document.json"));}
                catch(Exception ignored) { /* The previous index can still render the study text. */ }
                JsonObject readyDocument=refreshedDocument;
                deliver.accept(()->{
                    Runnable complete=()->{
                        if(readyDocument!=null)index=readyDocument;
                        if(command.equals("generate"))clearLiveSummary();
                        if(tutorCommand){tutorReply=null;setTutorBusy(false);}
                        else setBusy(false,choice==null?"원문 검색 완료":"AI 결과 생성 완료 · 원문 대조 필요");
                        finished.accept(result);
                    };
                    if(command.equals("generate"))finishLiveSummaryMotion();
                    if(tutorCommand && activeTutorMarker!=null)rememberTutorAnswer(activeTutorMarker,result);
                    if(tutorCommand && activeTutorMarker!=null && !reply.cancelled()) {
                        completeTutorStream(result,complete);
                    } else if(command.equals("generate") && liveSummaryTyping()) {
                        status.setText("강의 해설 생성 완료 · 화면에 구간 내용을 표시하는 중…");
                        liveSummaryCompletion=complete;startLiveSummaryTimer();
                    } else complete.run();
                });
            }catch(Exception error){
                JsonObject partial=command.equals("generate")?recoverPartial(target,ticket,str(request,"scope"),request.get("page").getAsInt(),index==null?"":str(index,"fingerprint")):null;
                deliver.accept(()->{
                    if(tutorCommand && error instanceof ChatReplyControl.Cancelled){
                        finishCancelledTutorReply();return;
                    }
                    if(command.equals("quiz")) {
                        quizGenerating=false;
                        setBusy(false,"문제 출제 중단 · 이전 문제는 유지됐어요.");
                        quiz.showGenerationFailure(error.getMessage()==null?"문제 출제를 완료하지 못했어요.":error.getMessage());
                        return;
                    }
                    if(command.equals("generate")||command.equals("group-plan")||command.equals("vision-plan"))
                        finishGeneration(true,"강의 해설 생성 중단");
                    if(command.equals("generate")) {clearLiveSummary();renderSummary(true);showConcepts(true);}
                    if(command.equals("tutor") && activeTutorMarker!=null) {
                        String marker=activeTutorMarker;activeTutorMarker=null;clearTutorStream();
                        for(TutorTurn turn:conversation)if(turn.marker.equals(marker))
                            turn.failure="답변을 완료하지 못했습니다. 다시 질문해 주세요.";
                        saveTutorConversation();renderTutor(true);
                    }
                    if(tutorCommand){
                        tutorReply=null;setTutorBusy(false);
                        if(isShowing())showError(error.getMessage()+"\n소요 시간: "+formatElapsed(System.nanoTime()-started));
                        return;
                    }
                    if(error.getMessage()!=null && error.getMessage().contains("크레딧이 부족해서")) {
                        if(partial!=null) {
                            products.put(resultProductKey(partial),partial);
                            selectProduct();renderSummary();showConcepts();
                        }
                        setBusy(false,"크레딧 부족 · 완료된 판단과 생성 결과는 보관됐어요.");
                        if(command.equals("generate"))finishGeneration(true,"크레딧 부족으로 중단 · 완료된 내용 보관됨");
                        if(automaticStudy)showGenerationError(error.getMessage());
                        else if(isShowing())CreditShortageDialog.show(this,error.getMessage());
                        return;
                    }
                    if(partial!=null) {
                        products.put(resultProductKey(partial),partial);
                        selectProduct();renderSummary();showConcepts();
                        if(str(partial,"kind").equals("ai_generated")) {
                            int pending=pendingStudyPageCount(partial);
                            setBusy(false,pending>0?"저장 결과 복구 · 원문 확인 필요 "+pending+"쪽":"강의 해설·개념 정리 생성 완료 · 저장 결과 복구");
                            finishGeneration(false,pending>0,pending>0
                                ?"강의 해설 생성 완료 · 원문 확인 필요 "+pending+"쪽":"강의 해설·개념 정리 완료");
                            if(!automaticStudy)showTimedReport("<html><body style='width:410px'><b>완료된 강의 해설·개념 정리를 복구했어요.</b>"
                                +"<br><br>마무리 처리 중 오류가 발생했지만 생성 결과는 저장돼 있어요."
                                +"<br>다시 생성할 필요는 없어요.</body></html>","강의 해설·개념 정리 결과 복구",started);
                            return;
                        }
                        setBusy(false,"AI 생성 중단 · 구간 "+partial.get("partialUnits").getAsInt()+"/"+partial.get("totalUnits").getAsInt()+"개 복구"
                            +(partial.has("integrationPending") && partial.get("integrationPending").getAsBoolean()?" · 통합 미완료":""));
                        finishGeneration(true,"강의 해설 중단 · 완료 구간은 저장됨");
                        String reason=error.getMessage()==null?"원인을 확인하지 못했습니다.":error.getMessage();
                        if(automaticStudy)showGenerationError(reason);
                        else showTimedReport("<html><body style='width:410px'><b>저장된 구간 "
                            +partial.get("partialUnits").getAsInt()+"/"+partial.get("totalUnits").getAsInt()
                            +"개를 복구했습니다.</b><br><br>중단 원인: "+escape(reason)
                            +"<br>완료된 결과와 유료 응답 캐시는 보존했습니다.</body></html>",
                            "강의 해설·개념 정리 생성 일부 복구",started);
                    } else {setBusy(false,"작업 중단 · 완료된 원문은 유지됨");if(command.equals("generate"))finishGeneration(true,"강의 해설 중단 · 다시 시도 가능");
                        showGenerationError(error.getMessage()+"\n소요 시간: "+formatElapsed(System.nanoTime()-started));}
                });
            }finally {
                if(attachmentDirectory!=null)try(var files=Files.list(attachmentDirectory)) {
                    for(Path file:files.toList())Files.deleteIfExists(file);
                }catch(Exception ignored) {}
                try {if(attachmentDirectory!=null)Files.deleteIfExists(attachmentDirectory);}catch(Exception ignored) {}
                for(Path transientAttachment:transientAttachments)
                    try {Files.deleteIfExists(transientAttachment);}catch(Exception ignored) {}
            }
        });
    }

    private JsonObject recoverPartial(PdfSource target,int ticket,String selectedScope,int selectedPage,String fingerprint) {
        return recoverPartial(target,ticket,summaryStrategyId(),selectedScope,selectedPage,fingerprint);
    }

    private JsonObject recoverPartial(PdfSource target,int ticket,String strategy,String selectedScope,int selectedPage,String fingerprint) {
        try {
            Path request=target.folder.resolve("requests/"+UUID.randomUUID()+".json");
            Files.createDirectories(request.getParent());
            JsonObject options=new JsonObject();options.addProperty("scope",selectedScope);options.addProperty("page",selectedPage);
            options.addProperty("strategy",strategy);
            Files.writeString(request,JSON.toJson(options),StandardCharsets.UTF_8);
            processes.run("pdf_ai.py",List.of("recover","--folder",target.folder.toString(),"--request",request.toString()),ticket,event->{});
            JsonObject result=readJson(request.resolveSibling(request.getFileName().toString().replace(".json",".result.json")));
            return recoverableGeneration(result,target.id,fingerprint) ? result : null;
        } catch(Exception ignored) {return null;}
    }

    static boolean recoverableGeneration(JsonObject result,String documentId,String fingerprint) {
        boolean finished=str(result,"kind").equals("ai_generated")
            && result.has("processingComplete") && result.get("processingComplete").isJsonPrimitive()
            && result.getAsJsonPrimitive("processingComplete").isBoolean()
            && result.get("processingComplete").getAsBoolean();
        return (str(result,"kind").equals("partial") || finished)
            && documentId.equals(str(result,"documentId"))
            && fingerprint.equals(str(result,"sourceFingerprint"));
    }

    private void navigate(String link) {
        if(link.startsWith("easy:")) {String key=link.substring(5);if(!expandedEasySummaries.add(key))expandedEasySummaries.remove(key);renderSummary(true);}
        else if(link.startsWith("page:")) {try{showPage(Integer.parseInt(link.substring(5)));sourceTabs.setSelectedIndex(0);}catch(NumberFormatException ignored){}}
        else if(link.startsWith("visual:"))showVisualDetail(link.substring(7));
        else if(link.startsWith("ask:")){question.setText(link.substring(4)+"에 대해 설명해줘.");showTutor();question.requestFocusInWindow();}
        else if(link.startsWith("tutor-evidence:")) {
            String marker=link.substring("tutor-evidence:".length());
            if(tutorAnswers.containsKey(marker)) {
                if(!expandedTutorEvidence.add(marker))expandedTutorEvidence.remove(marker);
                renderTutor(true);
            }
        }
        else if(link.startsWith("https://")) {
            try {URI url=URI.create(link);if(url.getHost()!=null && Desktop.isDesktopSupported())files.execute(()->{
                try {Desktop.getDesktop().browse(url);}catch(Exception ignored) {SwingUtilities.invokeLater(()->showError("웹 출처를 열지 못했습니다."));}
            });}catch(IllegalArgumentException ignored){}
        }
    }

    

    
    private void showTab(String name){
        if(name.equals("AI멘토") && tutorSideOpener!=null) {
            tutorSideOpener.run();
            return;
        }
        studyColumns.showView(name);
    }

    private void cancelAnalysis() {
        generation.incrementAndGet(); processes.cancel();releaseStudyAdmission();
        pendingGenerationReport=null;
        int stoppedProgress=summaryActivity.progress();
        automaticStudyError=null;
        setGenerationProgress(null);
        summaryActivity.setProgress(stoppedProgress);
        clearLiveSummary();
        setSummaryActivity(SummaryActivityBar.State.STOPPED);
        PdfSource target=source;
        if(target!=null&&!backgroundQuizzes.running(target.id))try{Files.writeString(target.folder.resolve("cancel"),"cancel",StandardCharsets.UTF_8);}catch(Exception ignored){}
        setBusy(false,"분석 취소 · 완료된 페이지는 재시도 시 재사용됩니다");

        selectProduct();renderSummary();showConcepts();updateOriginal();
    }
    private void clearLiveSummary(){
        firstSummaryShown=false;
        if(liveSummaryTimer!=null)liveSummaryTimer.stop();
        if(liveSummaryRefreshTimer!=null)liveSummaryRefreshTimer.stop();
        if(liveSummaryDraftTimer!=null)liveSummaryDraftTimer.stop();
        if(liveSummaryMotionTimer!=null)liveSummaryMotionTimer.stop();
        liveStreamPanes().forEach(p->{SummaryStreamText text=SummaryStreamText.of(p);if(text!=null)text.finish();});
        liveSummarySpaces.clear();
        liveSummaryDrafts.clear();liveSummaryDraftSequences.clear();liveSummaryDraftPanes.clear();liveSummaryDiscarded.clear();liveSummaryDraftStructureDirty=false;
        liveSummaryCompletion=null;liveGenerationKey=null;liveBatchOrder=-1;liveOverview=null;liveSummarySections.clear();
        liveOverviewStreamPane=null;liveOverviewEvidencePane=null;liveOverviewStreaming=false;liveOverviewComplete=false;liveOverviewSequence=0;
        liveConceptUnits.clear();
        liveSummaryVisible.clear();liveSummaryFades.clear();liveSummaryTotal=0;
    }
    private void setBusy(boolean value,String message){busy=value;status.setText(message);setControls();}
    private ChatReplyControl tutorReply;
    private void finishCancelledTutorReply(){
        String marker=activeTutorMarker;activeTutorMarker=null;clearTutorStream();
        for(TutorTurn turn:conversation)if(turn.marker.equals(marker))turn.failure="[답변 생성이 중지됐어요.]";
        tutorReply=null;setTutorBusy(false);saveTutorConversation();renderTutor(true);
    }
    private void cancelTutorReply(){
        if(!tutorBusy)return;
        if(tutorStreamCompletion!=null){
            Runnable complete=tutorStreamCompletion;tutorStreamCompletion=null;complete.run();return;
        }
        if(tutorReply!=null){tutorReply.cancel();setControls();}
    }
    private void setTutorBusy(boolean value){tutorBusy=value;setControls();}
    private void updateAutomaticStudyControls() {
        SummaryActivityBar.State state=summaryActivity.state();
        boolean running=state==SummaryActivityBar.State.RUNNING && busy;
        boolean retrying=state==SummaryActivityBar.State.STOPPED && !busy;
        automaticStudyAction.setText(running?"생성 중지":"다시 시도");
        automaticStudyAction.setVisible(!closed && source!=null && (running || retrying));
        automaticStudyStatus.setText(automaticStudyError==null?"":"<html>"+escape(automaticStudyError).replace("\n","<br>")+"</html>");
        automaticStudyStatus.setVisible(!closed && retrying && automaticStudyError!=null);
    }

    private void setControls(){
        if(automaticStudy)updateAutomaticStudyControls();
        updateTutorConnection();
        pageLabel.setText("/ "+(source==null?0:source.count));
        expandPdf.setEnabled(source!=null);
        for(JButton followUp:tutorFollowUps)followUp.setEnabled(index!=null&&!tutorBusy);
        imageReport.setEnabled(index!=null);analyzeImages.setEnabled(index!=null&&!busy);
        quiz.setReady(index!=null&&!busy);
        quiz.setGenerationReady(index!=null&&!busy&&!closed&&QuizGenerationData.ready(generated));
        quiz.setTutorReady(index!=null&&!busy&&!tutorBusy&&!closed);
        boolean cancellable=source!=null&&busy;
        cancel.setVisible(cancellable);cancel.setEnabled(cancellable);
        boolean retryAvailable=source!=null&&!busy&&!externalBatchActive
            && (index==null || index.has("incompletePages") && !index.getAsJsonArray("incompletePages").isEmpty());
        retry.setVisible(retryAvailable);retry.setEnabled(retryAvailable);
        recoveryRow.setVisible(cancellable || retryAvailable);
        String selected= switch(scope.getSelectedIndex()){case 1->"page";case 2->"section";default->"document";};
        JsonObject saved=products.get(productKey(selected,selected.equals("document")?0:page));
        boolean hasSaved=saved!=null && "ai_generated".equals(str(saved,"kind"));
        generate.setEnabled(index!=null&&!busy&&!externalBatchActive);
        generate.setText(hasSaved?"저장된 강의 해설 열기":saved!=null&&"partial".equals(str(saved,"kind"))
            ?"강의 해설 이어서 생성":"PDF 강의 해설·개념 정리 생성");
        regenerate.setVisible(hasSaved && !expectedStudyVersion().equals(str(saved,"promptVersion")));
        summaryStrategy.setEnabled(!busy&&!externalBatchActive);strategyComparison.setEnabled(index!=null&&!busy&&!externalBatchActive);scope.setEnabled(!busy&&!externalBatchActive);
        studyScope.setEnabled(scope.isEnabled());
        semanticCoverage.setVisible(generated!=null && generated.has("coverage"));
        semanticCoverage.setEnabled(!busy);
        regenerate.setEnabled(index!=null&&!busy&&!externalBatchActive);
        comparisonResults.setEnabled(comparisonReport!=null&&!busy);visual.setEnabled(index!=null&&!busy);
        visual.setText("이 페이지 전체 분석");ask.setEnabled(index!=null&&(!tutorBusy||tutorReply!=null&&!tutorReply.cancelled()));
        ask.setIcon(tutorBusy?ChatReplyControl.stopIcon():MistWorkspaceTheme.icon("send",16));
        ask.setToolTipText(tutorBusy?"답변 생성 중지":"질문 보내기");
        ask.getAccessibleContext().setAccessibleName(tutorBusy?"답변 생성 중지":"질문 보내기");
        tutorAttach.setEnabled(index!=null&&!tutorBusy);
        newChat.setEnabled(!tutorBusy);
        pageNumber.setEnabled(source!=null);thumbnailToggle.setEnabled(source!=null);zoom.setEnabled(source!=null);fullZoom.setEnabled(source!=null);
        zoomOut.setEnabled(source!=null);zoomIn.setEnabled(source!=null);
    }

    private void scrollSummaryToCurrentPage(){
        summaryScrollInteraction++;
        SummaryPageNavigator.Target target=SummaryPageNavigator.findNearest(summaryFlow,page);
        if(target==null){status.setText("현재 PDF "+page+"쪽을 근거로 한 강의 해설이 아직 없어요.");return;}
        SwingUtilities.invokeLater(()->{
            try{
                java.awt.geom.Rectangle2D bounds=target.pane().modelToView2D(target.offset());
                if(bounds==null)return;
                Rectangle location=SwingUtilities.convertRectangle(target.pane(),bounds.getBounds(),summaryFlow);
                summaryScroll.getViewport().setViewPosition(new Point(0,Math.max(0,Math.min(location.y,
                    summaryFlow.getHeight()-summaryScroll.getViewport().getHeight()))));
                summaryScrollInteraction++;
            }catch(javax.swing.text.BadLocationException ignored){status.setText("강의 해설 위치를 다시 확인해 주세요.");}
        });
    }

    private void updateTutorConnection(){
        boolean connected=source!=null&&index!=null;
        tutorConnection.setText(source==null?"PDF 연결 대기":!connected?"PDF 준비 중":busy?"PDF 분석 중 · 답변 가능":"PDF 연결됨");
        boolean strong=generated!=null&&!"partial".equals(str(generated,"kind"))&&(generated.has("overview")&&generated.get("overview").isJsonObject()&&!generated.getAsJsonObject("overview").isEmpty()
            ||generated.has("concepts")&&generated.get("concepts").isJsonArray()&&!generated.getAsJsonArray("concepts").isEmpty()
            ||generated.has("sections")&&generated.get("sections").isJsonArray()&&!generated.getAsJsonArray("sections").isEmpty());
        String state=busy?"강한 연결 시도 중":strong?"강한 연결 성공":"약한 연결";
        String name=source==null?"자료 없음":source.name;
        FontMetrics metrics=tutorDocumentConnection.getFontMetrics(tutorDocumentConnection.getFont());
        int room=Math.max(40,(tutorDocumentConnection.getWidth()>0?tutorDocumentConnection.getWidth():230)-metrics.stringWidth("PDF  · "+state));
        String shown=name;
        while(shown.codePointCount(0,shown.length())>1&&metrics.stringWidth(shown+"...")>room)
            shown=shown.substring(0,shown.offsetByCodePoints(shown.length(),-1));
        if(!shown.equals(name))shown+="...";
        tutorDocumentConnection.setText("PDF "+shown+" · "+state);
        tutorDocumentConnection.setToolTipText(name+" · "+state+" · "+tutorSearchHint.getText());
    }
    static String formatElapsed(long nanoseconds) {
        long milliseconds=Math.max(0,TimeUnit.NANOSECONDS.toMillis(nanoseconds));
        if(milliseconds<60_000)return String.format(Locale.KOREA,"%.1f초",milliseconds/1000d);
        long seconds=milliseconds/1000;
        if(seconds<3600)return seconds/60+"분 "+seconds%60+"초";
        return seconds/3600+"시간 "+(seconds%3600)/60+"분 "+seconds%60+"초";
    }
    private void showTimedReport(String reportHtml,String title,long started) {
        showTimedReport(reportHtml,title,started,0);
    }
    private void showTimedReport(String reportHtml,String title,long started,long preparationNanos) {
        JPanel content=new JPanel();content.setLayout(new BoxLayout(content,BoxLayout.Y_AXIS));
        content.add(new JLabel(reportHtml));
        content.add(Box.createVerticalStrut(10));
        long aiNanos=System.nanoTime()-started;
        JLabel elapsed=new JLabel("총 처리 시간: "+formatElapsed(preparationNanos+aiNanos));
        elapsed.setFont(StudyTheme.font(Font.BOLD,14));elapsed.setForeground(StudyTheme.INK);
        content.add(elapsed);
        Component report=content;
        int available=GraphicsEnvironment.isHeadless()?700:Math.max(300,GraphicsEnvironment.getLocalGraphicsEnvironment().getMaximumWindowBounds().height-180);
        if(content.getPreferredSize().height>available) {
            JScrollPane scroll=new SmoothScrollPane(content);scroll.setBorder(BorderFactory.createEmptyBorder());
            scroll.setPreferredSize(new Dimension(content.getPreferredSize().width+24,available));report=scroll;
        }
        Component displayed=report;
        if(!isShowing()) {
            if(generationProgress!=null && generationProgress.finished())
                pendingGenerationReport=()->JOptionPane.showMessageDialog(this,displayed,title,JOptionPane.INFORMATION_MESSAGE);
            return;
        }
        JOptionPane.showMessageDialog(this,displayed,title,JOptionPane.INFORMATION_MESSAGE);
    }
    public void showPendingGenerationReport() {
        if(!isShowing() || pendingGenerationReport==null)return;
        Runnable report=pendingGenerationReport;pendingGenerationReport=null;report.run();
    }
    private void showGenerationError(String message) {
        if(automaticStudy && summaryActivity.state()==SummaryActivityBar.State.STOPPED) {
            automaticStudyError=message==null || message.isBlank()?"강의 해설을 생성하지 못했어요.":message;
            updateAutomaticStudyControls();
        } else if(isShowing())showError(message);
        else pendingGenerationReport=()->showError(message);
    }
    private void showError(String message){JOptionPane.showMessageDialog(this,message,"PDF 작업",JOptionPane.INFORMATION_MESSAGE);}
    private void onEdt(int epoch,Runnable action){SwingUtilities.invokeLater(()->{if(!closed&&epoch==generation.get())action.run();});}
    private void onTutorEdt(int epoch,Runnable action){SwingUtilities.invokeLater(()->{if(!closed&&epoch==tutorGeneration.get())action.run();});}
    private void closeSource(PdfSource item){if(item!=null){Runnable action=()->{try{item.close();}catch(Exception ignored){}};try{renders.execute(action);}catch(RejectedExecutionException stopped){CompletableFuture.runAsync(action);}}}

    static boolean acceptsFiles(List<?> entries) {return entries.size()==1 && acceptsPdfFiles(entries);}
    static boolean acceptsPdfFiles(List<?> entries) {
        return !entries.isEmpty() && entries.stream().allMatch(entry->entry instanceof File file
            && file.isFile() && file.getName().toLowerCase(Locale.ROOT).endsWith(".pdf"));
    }
    private void installDropTargets(Component component) {
        if(GraphicsEnvironment.isHeadless()) return;
        // Keep native text dragging in editable search/question fields.
        if(component instanceof javax.swing.text.JTextComponent text && text.isEditable()) return;
        new DropTarget(component,DnDConstants.ACTION_COPY,new DropTargetAdapter(){
            @Override public void dragEnter(DropTargetDragEvent event){dragOver(event);}
            @Override public void dropActionChanged(DropTargetDragEvent event){dragOver(event);}
            @Override public void dragOver(DropTargetDragEvent event){
                // Finder can expose the file list only after acceptDrop. Reading it
                // during hover rejects an otherwise valid macOS file drag.
                boolean ok=event.isDataFlavorSupported(DataFlavor.javaFileListFlavor)
                    && (event.getSourceActions() & DnDConstants.ACTION_COPY)!=0;
                overlay.active=ok;dropLayer.repaint();
                if(ok)event.acceptDrag(DnDConstants.ACTION_COPY);else event.rejectDrag();
            }
            @Override public void dragExit(DropTargetEvent event){overlay.active=false;dropLayer.repaint();}
            @Override public void drop(DropTargetDropEvent event) {
                overlay.active=false;
                dropLayer.repaint();
                if(!event.isDataFlavorSupported(DataFlavor.javaFileListFlavor)
                        || (event.getSourceActions() & DnDConstants.ACTION_COPY)==0) {
                    event.rejectDrop();
                    return;
                }
                // Native file data may be unavailable until the drop is accepted.
                // Drag acceptance does not carry over to this separate drop event.
                event.acceptDrop(DnDConstants.ACTION_COPY);
                List<Path> files=List.of();
                try {
                    Object data=event.getTransferable().getTransferData(DataFlavor.javaFileListFlavor);
                    if(data instanceof List<?> entries && acceptsPdfFiles(entries)) {
                        files=entries.stream().map(entry->((File)entry).toPath()).toList();
                    } else {
                        status.setText("PDF 파일을 놓아 주세요. 파일이 실제로 저장되어 있는지도 확인해 주세요.");
                    }
                } catch(Exception error) {
                    status.setText("PDF 드롭 실패 · 다시 놓거나 ‘PDF 불러오기’를 이용해 주세요.");
                } finally {
                    // After acceptance, complete exactly once, including invalid files.
                    event.dropComplete(!files.isEmpty());
                }
                if(!files.isEmpty()) {
                    List<Path> selected=files;
                    SwingUtilities.invokeLater(()->importPdfs(selected));
                }
            }
        },true);
        if(component instanceof Container container) for(Component child:container.getComponents()) installDropTargets(child);
    }
    private final class DropOverlay extends LayerUI<JComponent> {
        boolean active;
        @Override public void installUI(JComponent component) {
            super.installUI(component);
            ((JLayer<?>)component).setLayerEventMask(AWTEvent.MOUSE_EVENT_MASK);
        }
        @Override public void uninstallUI(JComponent component) {
            ((JLayer<?>)component).setLayerEventMask(0);
            super.uninstallUI(component);
        }
        @Override protected void processMouseEvent(java.awt.event.MouseEvent event,
                                                   JLayer<? extends JComponent> layer) {
            if(event.getID()==java.awt.event.MouseEvent.MOUSE_PRESSED
                && SwingUtilities.isLeftMouseButton(event)){
                studyColumns.noteInteraction(event.getComponent());
                SummaryFlow.clearSelections(dropContent);
            }
        }
        @Override public void paint(Graphics graphics,JComponent component){super.paint(graphics,component);if(!active)return;Graphics2D g=(Graphics2D)graphics.create();g.setColor(new Color(12,19,35,190));g.fillRect(0,0,component.getWidth(),component.getHeight());g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setColor(Color.WHITE);g.setStroke(new BasicStroke(6,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));int x=component.getWidth()/2,y=component.getHeight()/2;g.drawLine(x-25,y,x+25,y);g.drawLine(x,y-25,x,y+25);g.setFont(new Font(UiFonts.FAMILY,Font.BOLD,16));String text="놓아서 PDF 분석 시작";g.drawString(text,x-g.getFontMetrics().stringWidth(text)/2,y+65);g.dispose();}
    }
    static JsonObject readJson(Path file)throws Exception{return JsonParser.parseString(Files.readString(file,StandardCharsets.UTF_8)).getAsJsonObject();}
    static String str(JsonObject object,String key){try{return object.has(key)&&!object.get(key).isJsonNull()?object.get(key).getAsString():"";}catch(Exception failure){return "";}}
    static String escape(String value){return StudyMarkdown.withoutControlChars(value).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\"","&quot;").replace("'","&#39;").replace("\n","<br>");}
    private static String pageLink(int page){return "<a href='page:"+page+"'>p."+page+"</a>";}
    private static Set<Integer> citationPages(JsonObject block){
        Set<Integer> pages=new TreeSet<>();
        if(block==null)return pages;
        JsonArray evidence=block.has("evidence") && block.get("evidence").isJsonArray()?block.getAsJsonArray("evidence"):null;
        if(evidence!=null)for(JsonElement item:evidence)if(item.isJsonObject()){
            JsonElement value=item.getAsJsonObject().get("page");
            if(value!=null && value.isJsonPrimitive())try{int page=value.getAsInt();if(page>0)pages.add(page);}catch(Exception ignored){}
        }
        JsonArray visual=block.has("visualPages") && block.get("visualPages").isJsonArray()?block.getAsJsonArray("visualPages"):null;
        if(visual!=null)for(JsonElement value:visual)try{int page=value.getAsInt();if(page>0)pages.add(page);}catch(Exception ignored){}
        return pages;
    }
    private String selectionOrigin(Map<String,StudySelectionContext.Source> sources,JsonObject block,String key,String title) {
        Set<Integer> pages=citationPages(block);
        if(block.has("pages")&&block.get("pages").isJsonArray())
            for(JsonElement item:block.getAsJsonArray("pages"))try{int number=item.getAsInt();if(number>0)pages.add(number);}catch(RuntimeException ignored){}
        return StudySelectionContext.register(sources,key,new StudySelectionContext.Source(source==null?"":source.id,
            title.isBlank()?"강의 해설":title,List.copyOf(pages)));
    }
    private static String headingCitations(JsonObject block){
        Set<Integer> pages=citationPages(block);
        if(pages.isEmpty())return "";
        StringBuilder out=new StringBuilder(" <small class='muted'>근거 ");
        int shown=0;for(int page:pages){if(shown++>=4)break;out.append(pageLink(page)).append(" &nbsp; ");}
        if(pages.size()>4)out.append("+").append(pages.size()-4);
        return out.append("</small>").toString();
    }
    private static String citations(JsonObject block){
        Set<Integer> pages=citationPages(block);
        if(pages.isEmpty())return "";
        StringBuilder out=new StringBuilder("<p class='muted'>근거 ");
        for(int page:pages)out.append(pageLink(page)).append(" &nbsp; ");
        return out.append("</p>").toString();
    }
    private static String documentHtml(String title,String body){return documentHtml(title,body,12);}
    private String summaryDocumentHtml(String title,String body,int fontSize){
        if(summaryReadingSkin)return SummarySkin.blackTextDocument(SummarySkin.document(title,body,fontSize));
        // SummaryFlow fills narrow viewports and caps wide ones.
        return SummarySkin.blackTextDocument(documentHtml(title,body,fontSize).replace("margin:14px 22px;",
            "margin:14px 12px;").replace("</style>",SummarySkin.headingSizes(fontSize)+"</style>"));
    }
    private static String documentHtml(String title,String body,int fontSize){return "<html><head><style>body{font-family:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif;font-size:"+fontSize+"pt;color:#182234;margin:14px 22px;line-height:1.45;}h1{font-size:"+Math.round(fontSize*1.75f)+"pt;margin-top:4px;margin-bottom:12px;}h2{font-size:"+Math.round(fontSize*1.30f)+"pt;margin-top:22px;margin-bottom:9px;}h3{font-size:"+Math.round(fontSize*1.14f)+"pt;margin-top:17px;margin-bottom:7px;}h4{color:#182234;font-weight:bold;font-size:"+fontSize+"pt;margin-top:18px;margin-bottom:7px;}p{margin-top:5px;margin-bottom:12px;}ol,ul{margin-top:7px;margin-bottom:13px;}li{margin-bottom:6px;}a{color:#76243d;text-decoration:none;}code{font-family:monospace;font-size:"+fontSize+"pt;background:#fafaf8;padding:2px 4px;}pre{font-family:monospace;font-size:"+fontSize+"pt;background:#fafaf8;padding:12px;margin-top:10px;margin-bottom:16px;}pre code{padding:0;}blockquote{background:#fafaf8;margin:10px 0;padding:10px;}table{margin-top:9px;margin-bottom:15px;}th{background:#f4e9ed;font-weight:bold;}td,th{padding:7px;}.muted{color:#6d7785;font-size:"+Math.max(6,Math.round(fontSize*.82f))+"pt;}.warning{background:#fff3dc;color:#825b14;padding:8px;}</style></head><body>"+(title.isEmpty()?"":"<h1>"+escape(title)+"</h1>")+body+"</body></html>";}
    boolean ready(){return index!=null&&!busy;}
    void previewOverlay(boolean value){overlay.active=value;dropLayer.repaint();}
    /** Returns the displayed physical PDF page (1-based), or null when no PDF is open. */
    public PdfLocation currentPdfLocation(){PdfSource current=source;return current==null?null:new PdfLocation(current.id,page,current.count);}
    public String currentPdfName(){PdfSource current=source;return current==null?"":current.name;}
    public Path currentPdfCopy(){PdfSource current=source;return current==null?null:current.folder.resolve("source.pdf");}
    /** Explicit library navigation may follow a queue, but never replace a local run. */
    public void showBatchGeneration(PdfBatchQueue.Snapshot snapshot) {
        if(snapshot==null || !PdfBatchQueue.active(snapshot.state()) || source==null
                || snapshot.storedPdf()==null || !isCurrentPdf(snapshot.storedPdf())
                || !source.id.equals(snapshot.documentId()) || snapshot.order()<observedBatchOrder)return;
        observeBatchState(snapshot);
        if(studyAdmission!=null || liveGenerationKey!=null && liveBatchOrder<0)return;
        selectGenerationEngine(snapshot.strategy());
    }
    /** An observed queue owns its generation; local navigation never cancels it. Call on EDT. */
    public void observeBatchState(PdfBatchQueue.Snapshot snapshot) {
        if(closed || source==null || snapshot.storedPdf()==null || !isCurrentPdf(snapshot.storedPdf())
                || !source.id.equals(snapshot.documentId()) || snapshot.order()<observedBatchOrder)return;
        boolean active=PdfBatchQueue.active(snapshot.state());
        if(active) {
            if(liveBatchOrder>=0 && snapshot.order()>liveBatchOrder)clearLiveSummary();
            externalBatchActive=true;observedBatchOrder=snapshot.order();
            if(liveGenerationKey==null || liveBatchOrder>=0) {
                summaryActivity.setProgress(snapshot.percent());
                setSummaryActivity(SummaryActivityBar.State.RUNNING);
            }
            setControls();return;
        }
        if(snapshot.order()!=observedBatchOrder)return;
        boolean wasActive=externalBatchActive;externalBatchActive=false;setControls();
        if(!wasActive)return;
        // A separately started local generation owns its own stream and completion.
        if(liveGenerationKey!=null && liveBatchOrder!=snapshot.order())return;
        PdfSource target=source;int epoch=generation.get();long order=observedBatchOrder;
        Runnable finish=()->{
            if(closed || source!=target || epoch!=generation.get() || order!=observedBatchOrder || externalBatchActive)return;
            clearLiveSummary();setSummaryActivity(SummaryActivityBar.State.IDLE);
            reloadGeneratedFromDisk();
        };
        if(liveSummaryTyping()) {liveSummaryCompletion=finish;startLiveSummaryTimer();}
        else finish.run();
    }

    public void acceptBatchStudyEvent(PdfBatchQueue.Snapshot snapshot,JsonObject event) {
        if(closed || source==null || snapshot.storedPdf()==null || !isCurrentPdf(snapshot.storedPdf())
                || !source.id.equals(snapshot.documentId()) || !PdfBatchQueue.active(snapshot.state())
                || snapshot.order()<observedBatchOrder || !summaryStrategyId().equals(snapshot.strategy())
                || !snapshot.strategy().equals(str(event,"strategy")))return;
        observeBatchState(snapshot);
        String key=productKey("document",0);
        if(liveGenerationKey==null) {
            clearLiveSummary();liveGenerationKey=key;liveBatchOrder=snapshot.order();setSummaryActivity(SummaryActivityBar.State.RUNNING);
        }
        if(!key.equals(liveGenerationKey) || liveBatchOrder!=snapshot.order())return;
        PdfSource target=source;int epoch=generation.get();long order=observedBatchOrder;
        JsonObject copy=event.deepCopy();
        jobs.execute(()->{
            if(source==target && epoch==generation.get() && order==observedBatchOrder && externalBatchActive)
                handleProgress(epoch,copy,order);
        });
    }

    public boolean reloadGeneratedFromDisk() {
        PdfSource current=source;
        if(current==null || index==null)return false;
        for(Path folder:strategyFolders(current.folder)) {
            Path latest=folder.resolve("latest-document-0.json");
            if(!Files.isRegularFile(latest))continue;
            try {
                JsonObject result=readJson(latest);
                if(!current.id.equals(str(result,"documentId")) || !compatibleFingerprint(result,index))continue;
                products.put(resultProductKey(result),result);
                if(summaryStrategyId().equals(str(result,"strategy")) || (summaryStrategyId().equals("page-v1") && str(result,"strategy").isEmpty())) {
                    selectProduct();renderSummary();fadeInSavedSummary();showConcepts();setControls();
                    return true;
                }
            } catch(Exception ignored) { /* A concurrent write can be read on the next open. */ }
        }
        return false;
    }
    public boolean isCurrentPdf(Path path) {
        PdfSource current=source;
        return current!=null && current.folder.resolve("source.pdf").toAbsolutePath().normalize()
            .equals(path.toAbsolutePath().normalize());
    }
    /** Stop work on a library item and release its PDF before its saved files are removed. Call on the EDT. */
    public CompletableFuture<Void> releasePdfIfMatches(String documentId) {
        CompletableFuture<Void> quizDone=backgroundQuizzes.cancel(documentId);
        PdfSource current=source;
        if(current==null || !current.id.equals(documentId))return quizDone;
        quizWorkbookOpenRevision++;
        PdfLocation previous=currentPdfLocation();
        generation.incrementAndGet();renderGeneration.incrementAndGet();processes.cancel();releaseStudyAdmission();
        hierarchyProjectionAttempts.clear();
        pendingGenerationReport=null;
        setGenerationProgress(null);
        tutorGeneration.incrementAndGet();tutorProcesses.cancel();tutorBusy=false;
        panelAnchorTimer.stop();panelLayoutAnchor=null;pendingLayoutAnchor=null;
        source=null;index=null;generated=null;comparisonReport=null;products.clear();clearLiveSummary();quizGenerating=false;quiz.reset(0,"");
        scrollPageTimer.stop();
        page=1;textSelection.reset();resetTutor();clearViewerImages();pageLayouts.clear();
        imageCanvas.removeAll();imageCanvas.add(pageImage);
        imageCanvas.setPreferredSize(new Dimension(320,400));imageCanvas.revalidate();imageCanvas.repaint();
        filename.setText("강의자료");filename.setToolTipText(null);
        pageNumber.setModel(new SpinnerNumberModel(1,1,1,1));pageLabel.setText("/ 0");
        firePropertyChange(PDF_LOCATION_PROPERTY,previous,null);
        setBusy(false,"PDF를 불러와 주세요.");
        summaryProsePanes.clear();summaryMathPanes.clear();summaryFormulaGroups.clear();summaryStepFlows.clear();
        summaryFlow.removeAll();summaryFlow.add(summary);summaryFlow.pruneMeasurements();
        setSummaryText(summary,"강의 해설","<p>PDF를 불러와 주세요.</p>",summaryFontSize.getValue());
        if(summaryScroll.getViewport().getView()!=summaryFlow)summaryScroll.setViewportView(summaryFlow);
        summaryFlow.revalidate();summaryScroll.getVerticalScrollBar().setValue(0);
        showConcepts();updateOriginal();
        CompletableFuture<Void> filesDone=CompletableFuture.runAsync(()->{},files);
        CompletableFuture<Void> jobsDone=CompletableFuture.runAsync(()->{},jobs);
        CompletableFuture<Void> tutorDone=CompletableFuture.runAsync(()->{},tutorJobs);
        CompletableFuture<Void> closedSource=CompletableFuture.runAsync(()->{
            try {current.close();}catch(IOException failure){throw new CompletionException(failure);}
        },renders);
        return CompletableFuture.allOf(filesDone,jobsDone,tutorDone,closedSource,quizDone);
    }
    int currentPage(){return page;}
    @Override public void close(){closeAndAwait();}

    /** Release Swing state on the EDT and report when its workers and pending writes finish. */
    public CompletableFuture<Void> closeAndAwait(){
        if(closeCompletion!=null)return closeCompletion;
        closeCompletion=new CompletableFuture<>();
        unwatchTutor.run();tutorThinkingTimer.stop();
        studyColumns.dispose();
        tutorScrollKeeper.close();
        pdfZoomMotion.clear();
        panelAnchorTimer.stop();panelLayoutAnchor=null;
        quizWorkbookOpenRevision++;
        summaryOutlineHover.close();
        summarySelection.close();conceptSelection.close();if(conceptOverview!=null)conceptOverview.dispose();
        summaryActivity.close();
        summaryScrollActivity.close();
        summaryOverviewLoading.close();
        if(tutorInputCard!=null)tutorInputCard.dispose();
        leavePdfOnly();tutorTimeTimer.stop();
        tutorViewportResizeTimer.stop();
        tutorResizeTimer.stop();tutorBubbles.clear();
        scrollPageTimer.stop();
        clearSummaryFade();
        if(studyTransition!=null)studyTransition.stop();
        if(sideStudyTransition!=null)sideStudyTransition.stop();
        clearTutorStream();
        clearLiveSummary();
        saveTutorConversation();
        closed=true;
        CompletableFuture<Void> quizDone=backgroundQuizzes.closeAndAwait();
        quizGenerating=false;quiz.reset(0,"");generation.incrementAndGet();renderGeneration.incrementAndGet();processes.close();releaseStudyAdmission();
        hierarchyProjectionAttempts.clear();
        setGenerationProgress(null);
        tutorGeneration.incrementAndGet();tutorProcesses.close();
        clearTutorAttachments();
        files.shutdown();jobs.shutdown();tutorJobs.shutdown();closeSource(source);source=null;renders.shutdown();
        CompletableFuture<Void> studyDone=new CompletableFuture<>(),tutorDone=new CompletableFuture<>();
        processes.afterIdle(()->studyDone.complete(null));
        tutorProcesses.afterIdle(()->tutorDone.complete(null));
        CompletableFuture.allOf(studyDone,tutorDone,quizDone).thenRunAsync(()->{
            try {
                for(ExecutorService executor:List.of(files,jobs,tutorJobs,renders))
                    if(!executor.awaitTermination(30,TimeUnit.SECONDS))throw new TimeoutException("학습 파일 정리가 끝나지 않았어요.");
            } catch(InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new CompletionException(interrupted);
            } catch(TimeoutException timeout) {
                throw new CompletionException(timeout);
            }
        }).whenComplete((ignored,failure)->{
            if(failure==null)closeCompletion.complete(null);
            else closeCompletion.completeExceptionally(failure);
        });
        return closeCompletion;
    }
}
