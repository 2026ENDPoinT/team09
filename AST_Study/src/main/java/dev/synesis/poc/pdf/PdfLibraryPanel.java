package dev.synesis.poc.pdf;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import dev.synesis.poc.ui.StudyTheme;
import dev.synesis.poc.ui.LibraryDesign;

import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.rendering.PDFRenderer;

import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import javax.swing.event.DocumentEvent;
import javax.swing.event.DocumentListener;
import javax.swing.plaf.LayerUI;
import java.awt.*;
import java.awt.datatransfer.DataFlavor;
import java.awt.datatransfer.Transferable;
import java.awt.datatransfer.UnsupportedFlavorException;
import java.awt.dnd.*;
import java.awt.image.BufferedImage;
import java.awt.geom.Path2D;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.DigestInputStream;
import java.io.OutputStream;
import java.util.HexFormat;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;
import java.util.function.Function;

/** Document shelf backed by the PDF copies already stored in .synesis/pdf. */
public final class PdfLibraryPanel extends JPanel implements AutoCloseable {
    private static final Color BACKGROUND = LibraryDesign.CANVAS, BORDER = LibraryDesign.LINE,
            TEXT = LibraryDesign.INK, MUTED = LibraryDesign.MUTED, BLUE = LibraryDesign.INK;
    private static final DateTimeFormatter DATE = DateTimeFormatter.ofPattern("yyyy-MM-dd");
    private static final DateTimeFormatter DATE_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm");
    private static final String[][] FOLDER_ICONS = {
        {"folder","아이콘 없음"},{"math","수식"},{"book","책"},{"atom","물리"},
        {"flask","화학"},{"globe","지리"},{"chart","통계"},{"code","코딩"},
        {"music","음악"},{"medical","의학"},{"star","즐겨찾기"},{"heart","관심"},
        {"bulb","아이디어"},{"pencil","필기"},{"calendar","일정"},{"camera","사진"},
        {"briefcase","업무"},{"graduation","학업"},{"language","언어"},{"leaf","생물"},
        {"palette","미술"},{"bolt","전기"},{"target","목표"},{"computer","컴퓨터"}
    };
    private static final String[][] FOLDER_COLORS = {
        {"빨강","#f52238"},{"다홍","#ff4324"},{"주황","#ff7900"},{"골드","#ffad00"},
        {"노랑","#f5ce00"},{"라임","#b4d900"},{"연두","#68d018"},{"초록","#08b85b"},
        {"청록","#00ae95"},{"민트","#00ccb2"},{"하늘","#00b7ef"},{"파랑","#1474ff"},
        {"남색","#304cf0"},{"인디고","#6337f5"},{"보라","#a02af0"},{"자주","#cf16b0"},
        {"분홍","#f52b92"},{"버건디","#ce174d"},{"흰색","#ffffff"},{"검정","#242424"}
    };
    private final Path root;
    private final Consumer<Path> open;
    private final Consumer<List<Path>> importMany;
    private final Function<String,CompletableFuture<Void>> releaseDocument;
    private final Consumer<String> navigate;
    private final ExecutorService loader = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "pdf-library"); thread.setDaemon(true); return thread;
    });
    private final JPanel grid = new JPanel();
    private final JPanel emptyFolderState = new JPanel(new GridBagLayout());
    private final Map<String,JComponent> folderIcons = new HashMap<>();
    private final Map<String,JPanel> folderCards = new HashMap<>();
    private final Map<String,JPanel> documentCards = new HashMap<>();
    private final Map<String,Integer> pageCounts = new java.util.concurrent.ConcurrentHashMap<>();
    private final Map<String,JLabel> pageCountLabels = new HashMap<>();
    private boolean listView;
    private static final int LIST_MIN_WIDTH=700;
    private final JPanel shelf = new LibraryShelf();
    private final JScrollPane scroll = new dev.synesis.poc.ui.SmoothScrollPane(shelf);
    private final JPanel libraryContent = new JPanel(new BorderLayout());
    private final dev.synesis.poc.ui.LibraryAdBanner promotion = new dev.synesis.poc.ui.LibraryAdBanner();
    private final CardLayout mainCards = new CardLayout();
    private final JPanel mainViews = new JPanel(mainCards);
    private final dev.synesis.poc.ui.LibrarySectionMotion sectionMotion=new dev.synesis.poc.ui.LibrarySectionMotion(mainViews);
    private boolean replayItems=true;
    private final JLabel profileSubtitle = new JLabel("사용량 집계 기간을 읽고 있어요…");
    private final JButton resetStatistics = new JButton("초기화 · 개발자용");
    private boolean resettingStatistics;
    private final JLabel profileTokens = new JLabel("—");
    private final JLabel profileCost = new JLabel("—");
    private final JLabel profileUsedCredits = new JLabel("—");
    private final JLabel profileAverageCredits = new JLabel("—");
    private final JLabel profileRemainingCredits = new JLabel("—");
    private final JLabel profileWalletDetail = new JLabel("크레딧 지갑을 읽고 있어요…");
    private final JLabel profilePlan = new JLabel("—");
    private final JLabel profilePlanState = new JLabel("확인 중");
    private final JLabel profileCreditSummary = new JLabel("크레딧을 확인하고 있어요.");
    private final JProgressBar profileCreditProgress = new JProgressBar(0,1000);
    private final JLabel profilePurchasedAt = new JLabel("—");
    private final JLabel profileNextPaymentAt = new JLabel("—");
    private final JLabel profileAutoRenew = new JLabel("—");
    private final JButton rechargeCredits = new JButton("충전하기");
    private CreditWallet.Snapshot creditSnapshot;
    private final JLabel profilePdfCount = new JLabel("—");
    private final JLabel profileDetail = new JLabel("사용량을 읽고 있어요…");
    private final DropOverlay dropOverlay = new DropOverlay();
    private final JLayer<JComponent> dropLayer = new JLayer<>(libraryContent,dropOverlay);
    private final javax.swing.Timer hideDropOverlay = new javax.swing.Timer(120,event->setDropOverlay(false));
    private final JTextField search = new JTextField(18);
    private final JLabel sectionCount = new JLabel();
    private final JPanel breadcrumbs = new JPanel(new FlowLayout(FlowLayout.LEFT,4,0));
    private final Map<String,JButton> breadcrumbTargets = new HashMap<>();
    private final Map<String,String> pendingImports = new java.util.concurrent.ConcurrentHashMap<>();
    private PdfLibraryOrganization organization;
    private String currentFolderId="";
    private String hoverFolderId;
    private JComponent hoverFolderTarget;
    private int folderBlinkCount;
    private final javax.swing.Timer folderHover = new javax.swing.Timer(700,event -> beginFolderBlink());
    private final javax.swing.Timer folderBlink = new javax.swing.Timer(100,event -> advanceFolderBlink());
    private javax.swing.Timer flyingTimer;
    private Runnable flyingCompletion,flyingInterrupted;
    private LibraryDrag activeDocumentDrag;
    private DragSourceMotionListener selectionDragListener;
    private Runnable cancelSelectionDrag;
    private static final DataFlavor DOCUMENT_FLAVOR = new DataFlavor(
        DataFlavor.javaJVMLocalObjectMimeType+";class="+LibraryDrag.class.getName(),"SYNESIS 자료");
    private record LibraryDrag(String id,boolean folder,BufferedImage preview,List<String> documentIds) {
        LibraryDrag {documentIds=List.copyOf(documentIds);}
        LibraryDrag(String id,boolean folder,BufferedImage preview) {this(id,folder,preview,folder?List.of():List.of(id));}
        LibraryDrag(String id,boolean folder) {this(id,folder,null);}
    }
    private static final int LIBRARY_DRAG_THRESHOLD=Math.max(8,DragSource.getDragThreshold());
    private final JButton selectionToggle = new JButton("일괄 선택");
    private final JPanel bulkBar = new BulkSelectionBar();
    private final JLabel selectedCount = new JLabel("0개 선택");
    private final JButton selectAll = new JButton("현재 페이지 모두 선택");
    private final JButton clearSelection = new JButton("선택 해제");
    private final JButton deleteSelectedFiles = new JButton("휴지통으로 이동시키기");
    private final JButton restoreSelected = new JButton("일괄 복원");
    private final JButton deleteSelectedData = new JButton("선택된 파일 데이터 삭제");
    private final Set<String> selectedIds = new HashSet<>();
    private final Set<String> selectedFolderIds = new HashSet<>();
    private boolean selectionMode;
    private boolean recentFirst=true;
    private boolean recentSection;
    private boolean profileSection;
    private boolean plannerSection;
    private dev.synesis.poc.ui.PlannerDesign plannerView;
    public void assistantDataChanged(){if(plannerView!=null)plannerView.refreshFromStore();if(profileSection)refreshProfile();}
    private int profileRevision;
    private final Map<String,JLabel> covers = new HashMap<>();
    private final Map<String,ImageIcon> thumbnails = new java.util.concurrent.ConcurrentHashMap<>();
    private record CoverVersion(long sourceModified,long sourceSize,long previewModified) {}
    private record CachedCover(CoverVersion version,ImageIcon image) {}
    private final Map<String,CachedCover> thumbnailCache=new java.util.concurrent.ConcurrentHashMap<>();
    private final javax.swing.Timer searchDelay=new javax.swing.Timer(120,e->showItems());
    private final AssistantUi assistantUi=new AssistantUi();
    public AssistantLibraryUi assistantLibraryUi(){return assistantUi;}
    private List<PdfLibraryStore.Item> items = List.of();
    private java.util.function.Consumer<List<Path>> pdfDropHandler;
    private List<PdfBatchQueue.Snapshot> importSnapshots=List.of();
    private String pendingImportKey="";
    public void setPdfDropHandler(java.util.function.Consumer<List<Path>> handler){pdfDropHandler=handler;}
    public void showImportHome(){search.setText("");showLibraryNow(false);}
    private List<PdfBatchQueue.Snapshot> pendingImportCards(){
        Set<String> stored=new HashSet<>();for(var item:items)stored.add(item.id());
        return importSnapshots.stream().filter(s->s.state()!=PdfBatchQueue.State.FAILED
            && s.state()!=PdfBatchQueue.State.CANCELLED && s.state()!=PdfBatchQueue.State.DECLINED
            && (s.documentId()==null||!stored.contains(s.documentId()))).toList();
    }
    private String pendingImportKey(){return pendingImportCards().stream().map(s->Long.toString(s.order())).collect(java.util.stream.Collectors.joining(","));}
    public void setImportSnapshots(List<PdfBatchQueue.Snapshot> snapshots){
        importSnapshots=List.copyOf(snapshots);
        if(!pendingImportKey.equals(pendingImportKey()))showItems();
    }
    private volatile int revision;
    private Runnable logoutHandler = () -> {};

    public void setLogoutHandler(Runnable handler) { logoutHandler=handler; }

    public void showHome() { showLibrarySection(false); }

    /** Use the shelf's display name before opening the stored source.pdf during navigation. */
    public String documentDisplayName(Path path) {
        Path target=path.toAbsolutePath().normalize();
        for(PdfLibraryStore.Item item:items)
            if(item.source().toAbsolutePath().normalize().equals(target))return item.name();
        return path.getFileName().toString();
    }

    public PdfLibraryPanel(Consumer<Path> open) {
        this(PdfLibraryStore.defaultRoot(),open,id->CompletableFuture.completedFuture(null),section->{});
    }

    public PdfLibraryPanel(Consumer<Path> open, Function<String,CompletableFuture<Void>> releaseDocument) {
        this(PdfLibraryStore.defaultRoot(),open,releaseDocument,section->{});
    }

    public PdfLibraryPanel(Consumer<Path> open, Function<String,CompletableFuture<Void>> releaseDocument,
                           Consumer<String> navigate) {
        this(PdfLibraryStore.defaultRoot(),open,releaseDocument,navigate);
    }

    public PdfLibraryPanel(Consumer<Path> open, Function<String,CompletableFuture<Void>> releaseDocument,
                           Consumer<String> navigate, Consumer<List<Path>> importMany) {
        this(PdfLibraryStore.defaultRoot(),open,releaseDocument,navigate,importMany);
    }

    PdfLibraryPanel(Path root, Consumer<Path> open) {
        this(root,open,id->CompletableFuture.completedFuture(null),section->{});
    }

    PdfLibraryPanel(Path root, Consumer<Path> open,
                    Function<String,CompletableFuture<Void>> releaseDocument) {
        this(root,open,releaseDocument,section->{});
    }

    PdfLibraryPanel(Path root, Consumer<Path> open,
                    Function<String,CompletableFuture<Void>> releaseDocument, Consumer<String> navigate) {
        this(root,open,releaseDocument,navigate,paths->paths.forEach(open));
    }

    PdfLibraryPanel(Path root, Consumer<Path> open,
                    Function<String,CompletableFuture<Void>> releaseDocument, Consumer<String> navigate,
                    Consumer<List<Path>> importMany) {
        super(new BorderLayout());
        this.root = root; this.open = open; this.importMany=importMany;
        this.releaseDocument=releaseDocument; this.navigate=navigate;
        ((dev.synesis.poc.ui.FadeScrollPane)scroll).setVerticalOverflowShadow(true);
        setBackground(BACKGROUND);
        add(LibraryDesign.header(this::showProfileSection),BorderLayout.NORTH);
        libraryContent.setBackground(BACKGROUND);
        hideDropOverlay.setRepeats(false);
        libraryContent.add(sidebar(), BorderLayout.WEST);
        JPanel main = new JPanel(new BorderLayout()); main.setBackground(BACKGROUND);
        JPanel heading = new JPanel(new BorderLayout());
        heading.setOpaque(false); heading.setBorder(new EmptyBorder(37, 37, 0, 37));
        JPanel labels = new JPanel(); labels.setOpaque(false);
        labels.setLayout(new BoxLayout(labels, BoxLayout.Y_AXIS));
        JLabel title = new JLabel("내 학습 자료"); title.setForeground(TEXT);
        title.setFont(LibraryDesign.font(Font.BOLD,32)); title.setPreferredSize(new Dimension(300,44));
        title.setMaximumSize(new Dimension(Integer.MAX_VALUE,44));labels.add(title);
        labels.add(Box.createVerticalStrut(4));
        JLabel subtitleFirst = new JLabel("파일을 편하게 모아두고");
        JLabel subtitleSecond = new JLabel("정리는 Personal 에이전트에게 맡기세요!");
        Font subtitleFont=LibraryDesign.font(Font.PLAIN,14);
        for(JLabel line:new JLabel[]{subtitleFirst,subtitleSecond}) {
            line.setForeground(MUTED);line.setFont(subtitleFont);
            line.setBorder(new EmptyBorder(1,0,1,0));
            line.setAlignmentX(Component.LEFT_ALIGNMENT);
        }
        labels.add(subtitleFirst);labels.add(Box.createVerticalStrut(2));labels.add(subtitleSecond);
        Dimension labelSize=labels.getPreferredSize();
        labels.setPreferredSize(new Dimension(Math.max(480,labelSize.width),labelSize.height));
        JPanel tools = new JPanel(new FlowLayout(FlowLayout.RIGHT, 0, 0)); tools.setOpaque(false);
        search.setToolTipText("자료 이름이나 과목 검색");
        search.setPreferredSize(new Dimension(420, 48));
        searchDelay.setRepeats(false);
        search.getDocument().addDocumentListener(new DocumentListener() {
            private void update(){if(search.getText().isEmpty()||!isShowing())showItems();else searchDelay.restart();}
            public void insertUpdate(DocumentEvent event) { update(); }
            public void removeUpdate(DocumentEvent event) { update(); }
            public void changedUpdate(DocumentEvent event) { update(); }
        });
        JButton add = new JButton("새로 만들기",LibraryDesign.icon("add",18,18)); LibraryDesign.button(add,true);
        add.setIconTextGap(8);add.setPreferredSize(new Dimension(148,48));
        tools.setBorder(new EmptyBorder(12,0,12,0));
        JPopupMenu createMenu=new JPopupMenu();
        JMenuItem importPdf=new JMenuItem("PDF 불러오기");
        importPdf.addActionListener(event -> choosePdf());
        JMenuItem createFolder=new JMenuItem("새 폴더 만들기");
        createFolder.addActionListener(event -> createFolder());
        createMenu.add(importPdf);createMenu.add(createFolder);
        add.addActionListener(event -> showContextMenu(createMenu,add,0,add.getHeight()));
        LibraryDesign.button(selectionToggle,false);
        selectionToggle.setBorder(new LibraryDesign.RoundedBorder(8,LibraryDesign.LINE,new Insets(0,16,0,16)) {
            @Override public void paintBorder(Component c,Graphics graphics,int x,int y,int w,int h) {
                Graphics2D g=(Graphics2D)graphics.create();
                try {
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                    boolean active=selectionToggle.isSelected();
                    Color fill=selectionToggle.getBackground();
                    if(selectionToggle.getModel().isPressed())fill=active?new Color(0x1d4ed8):new Color(0xededed);
                    else if(selectionToggle.getModel().isRollover())fill=active?new Color(0x2563eb):new Color(0xf6f6f6);
                    g.setColor(fill);g.fillRoundRect(x,y,w-1,h-1,16,16);
                    g.setColor(active?new Color(0x2563eb):LibraryDesign.LINE);g.drawRoundRect(x,y,w-1,h-1,16,16);
                } finally {g.dispose();}
            }
        });
        selectionToggle.setPreferredSize(new Dimension(100,48));
        selectionToggle.addActionListener(event -> {
            selectionMode=!selectionMode;
            if(!selectionMode){selectedIds.clear();selectedFolderIds.clear();}
            showItems();
        });
        tools.add(add);
        JPanel titleRow=new JPanel(new BorderLayout());titleRow.setOpaque(false);
        titleRow.add(labels,BorderLayout.WEST);titleRow.add(tools,BorderLayout.EAST);
        heading.add(titleRow,BorderLayout.NORTH);
        JPanel promotionSlot=new JPanel(new BorderLayout());promotionSlot.setOpaque(false);
        promotionSlot.setBorder(new EmptyBorder(28,37,28,37));promotionSlot.add(promotion);
        JPanel filters = new JPanel(new BorderLayout(12,0)); filters.setOpaque(false);
        filters.setBorder(new EmptyBorder(0,37,0,37));
        filters.add(LibraryDesign.searchField(search),BorderLayout.CENTER);
        JPanel filterActions = new JPanel();filterActions.setOpaque(false);
        filterActions.setLayout(new BoxLayout(filterActions,BoxLayout.X_AXIS));
        JButton recent = new JButton("최근 열람"), byName = new JButton("이름순");
        LibraryDesign.button(recent,true);LibraryDesign.button(byName,false);
        recent.setPreferredSize(new Dimension(108,48));byName.setPreferredSize(new Dimension(84,48));
        recent.setMinimumSize(new Dimension(108,48));recent.setMaximumSize(new Dimension(108,48));
        byName.setMinimumSize(new Dimension(84,48));byName.setMaximumSize(new Dimension(84,48));
        selectionToggle.setMinimumSize(new Dimension(100,48));selectionToggle.setMaximumSize(new Dimension(100,48));
        recent.addActionListener(event->{recentFirst=true;LibraryDesign.button(recent,true);LibraryDesign.button(byName,false);showItems();});
        byName.addActionListener(event->{recentFirst=false;LibraryDesign.button(recent,false);LibraryDesign.button(byName,true);showItems();});
        filterActions.add(recent);filterActions.add(Box.createHorizontalStrut(12));
        filterActions.add(byName);filterActions.add(Box.createHorizontalStrut(12));filterActions.add(selectionToggle);
        filters.add(filterActions,BorderLayout.EAST);
        bulkBar.setOpaque(false);
        selectedCount.setForeground(TEXT);selectedCount.setFont(LibraryDesign.medium(13));
        selectedCount.setPreferredSize(new Dimension(84,36));
        for(JButton button:new JButton[]{selectAll,clearSelection,restoreSelected,deleteSelectedFiles,deleteSelectedData}) {
            LibraryDesign.button(button,button==selectAll);
            button.setFont(LibraryDesign.medium(13));
            Dimension size=button.getPreferredSize();button.setPreferredSize(new Dimension(size.width,36));
        }
        deleteSelectedFiles.setForeground(new Color(0xb93838));
        deleteSelectedData.setForeground(new Color(0xb93838));
        selectAll.addActionListener(event -> {
            for(PdfLibraryStore.Item item:items)if(visibleDocument(item))selectedIds.add(item.id());
            if(!recentSection&&organization!=null)for(var folder:organization.folders())
                if(visibleFolder(folder)&&!PdfLibraryOrganization.isTrash(folder.id()))selectedFolderIds.add(folder.id());
            showItems();
        });
        clearSelection.addActionListener(event -> {completeSelectionAction();showItems();});
        restoreSelected.addActionListener(event -> restoreSelection(List.copyOf(selectedIds),List.copyOf(selectedFolderIds)));
        deleteSelectedFiles.addActionListener(event -> deleteSelected(true));
        deleteSelectedData.addActionListener(event -> deleteSelected(false));
        bulkBar.add(selectedCount);bulkBar.add(selectAll);bulkBar.add(clearSelection);
        bulkBar.add(restoreSelected);bulkBar.add(deleteSelectedFiles);bulkBar.add(deleteSelectedData);
        JPanel stickyTools=new JPanel(new BorderLayout());stickyTools.setBackground(BACKGROUND);
        stickyTools.setBorder(new EmptyBorder(0,0,30,0));
        stickyTools.add(filters,BorderLayout.NORTH);stickyTools.add(bulkBar,BorderLayout.SOUTH);
        updateSelectionControls();
        main.add(heading, BorderLayout.NORTH);
        dev.synesis.poc.ui.LibraryStickyShelf scrollingShelf=new dev.synesis.poc.ui.LibraryStickyShelf(
            promotionSlot,stickyTools,shelf,()->!listView||scroll.getViewport().getWidth()>=LIST_MIN_WIDTH+74);
        scroll.setViewportView(scrollingShelf);
        scroll.getViewport().addChangeListener(event->{
            scrollingShelf.viewportChanged();
            boolean pinned=scrollingShelf.toolbarPinned();
            scroll.putClientProperty("synesis.pinnedToolbar",pinned);
            // A moving sticky toolbar needs its old and new pixels repainted;
            // ordinary shelf scrolling can copy unchanged pixels without a cache.
            ((dev.synesis.poc.ui.SmoothScrollPane)scroll).setVerticalScrollReuseEnabled(!pinned);
        });
        grid.setBackground(BACKGROUND); grid.setBorder(new EmptyBorder(20, 37, 36, 37));
        // Keep the outer BoxLayout centered even when the list rows align their own cells left.
        grid.setAlignmentX(Component.CENTER_ALIGNMENT);
        shelf.setBackground(BACKGROUND);
        JPanel shelfTop=new JPanel();shelfTop.setBackground(BACKGROUND);
        shelfTop.setLayout(new BoxLayout(shelfTop,BoxLayout.Y_AXIS));
        JPanel section=new JPanel(new BorderLayout());section.setBackground(BACKGROUND);
        section.setBorder(new EmptyBorder(28,37,0,37));
        JLabel sectionTitle=new JLabel("내 문서");
        sectionTitle.setFont(LibraryDesign.font(Font.BOLD,18));sectionTitle.setForeground(TEXT);
        sectionTitle.setPreferredSize(new Dimension(60,32));
        JPanel sectionPath=new JPanel(new FlowLayout(FlowLayout.LEFT,0,0));sectionPath.setOpaque(false);
        sectionTitle.setBorder(new EmptyBorder(0,0,0,0));
        breadcrumbs.setBorder(new EmptyBorder(0,16,0,0));
        breadcrumbs.setOpaque(false);
        sectionPath.add(sectionTitle);sectionPath.add(breadcrumbs);
        section.add(sectionPath,BorderLayout.WEST);
        sectionCount.setFont(LibraryDesign.font(Font.PLAIN,12));sectionCount.setForeground(MUTED);
        JPanel viewControls=new JPanel();viewControls.setOpaque(false);viewControls.setLayout(new BoxLayout(viewControls,BoxLayout.X_AXIS));
        viewControls.add(sectionCount);viewControls.add(Box.createHorizontalStrut(16));viewControls.add(LibraryDesign.viewSwitch(list->{
            if(listView==list)return;listView=list;replayItems=true;showItems();scroll.getViewport().setViewPosition(new Point());
        }));
        section.add(viewControls,BorderLayout.EAST);
        shelfTop.add(section);shelfTop.add(grid);
        emptyFolderState.setOpaque(false);
        emptyFolderState.setAlignmentX(Component.CENTER_ALIGNMENT);
        emptyFolderState.setMaximumSize(new Dimension(Integer.MAX_VALUE,300));
        emptyFolderState.setPreferredSize(new Dimension(500,280));
        JPanel emptyMessage=new JPanel();emptyMessage.setOpaque(false);
        emptyMessage.setLayout(new BoxLayout(emptyMessage,BoxLayout.Y_AXIS));
        JLabel emptyTitle=new JLabel("이 파일엔 아무 것도 없어요!");
        emptyTitle.setFont(LibraryDesign.font(Font.BOLD,17));emptyTitle.setForeground(MUTED);
        emptyTitle.setAlignmentX(Component.CENTER_ALIGNMENT);
        emptyMessage.add(emptyTitle);emptyMessage.add(Box.createVerticalStrut(22));
        JComponent cat=new SleepingCat();cat.setAlignmentX(Component.CENTER_ALIGNMENT);
        emptyMessage.add(cat);
        emptyFolderState.add(emptyMessage);
        emptyFolderState.setVisible(false);shelfTop.add(emptyFolderState);
        shelf.add(shelfTop, BorderLayout.NORTH);
        installContextMenu(grid,createMenu,false);
        installContextMenu(shelf,createMenu,false);
        installContextMenu(scroll.getViewport(),createMenu,false);
        installContextMenu(emptyFolderState,createMenu,true);
        scroll.setBorder(null); scroll.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
        scroll.getViewport().setBackground(BACKGROUND);
        scroll.getViewport().addComponentListener(new java.awt.event.ComponentAdapter() {
            @Override public void componentResized(java.awt.event.ComponentEvent event) { setColumns(); }
        });
        main.add(scroll, BorderLayout.CENTER);
        mainViews.add(main,"documents");
        mainViews.add(profilePanel(),"profile");
        plannerView=new dev.synesis.poc.ui.PlannerDesign();
        dev.synesis.poc.ui.FadeScrollPane plannerScroll=new dev.synesis.poc.ui.FadeScrollPane(plannerView);
        plannerScroll.setVerticalOverflowShadow(true);
        plannerScroll.setScrollCacheEnabled(true);
        plannerScroll.setBorder(null);
        plannerScroll.getViewport().setBackground(Color.WHITE);
        plannerScroll.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
        plannerScroll.getVerticalScrollBar().setUI(new dev.synesis.poc.ui.FadingScrollBarUI(Color.BLACK,.18f));
        mainViews.add(plannerScroll,"planner");
        libraryContent.add(sectionMotion.component(),BorderLayout.CENTER);
        add(dropLayer,BorderLayout.CENTER);
        folderHover.setRepeats(false);
        folderBlink.setRepeats(true);
        installDrop(this);
        addHierarchyListener(event->{
            if((event.getChangeFlags()&java.awt.event.HierarchyEvent.SHOWING_CHANGED)!=0&&!isShowing())
                finishSelectionDrag();
            if((event.getChangeFlags()&java.awt.event.HierarchyEvent.SHOWING_CHANGED)!=0&&isShowing()) {
                int index=0;for(Component component:grid.getComponents())
                    if(component instanceof AnimatedCard card)card.entrance(index++,true);
                grid.repaint();
            }
        });
        refresh();
    }

    private JPanel sidebar() {
        return new dev.synesis.poc.ui.LibrarySidebar(()->!recentSection&&!profileSection&&!plannerSection,
            ()->plannerSection,()->showLibrarySection(false),this::showPlannerSection,this::showProfileSection);
    }

    /** Only the two chrome bars move; files and folders stay in the static departure capture. */
    public List<dev.synesis.poc.ui.LibraryDeparture.Part> departureParts() {
        List<dev.synesis.poc.ui.LibraryDeparture.Part> parts=new ArrayList<>();
        Component top=((BorderLayout)getLayout()).getLayoutComponent(BorderLayout.NORTH);
        Component side=((BorderLayout)libraryContent.getLayout()).getLayoutComponent(BorderLayout.WEST);
        if(top instanceof JComponent header)parts.add(new dev.synesis.poc.ui.LibraryDeparture.Part(header,dev.synesis.poc.ui.LibraryDeparture.Kind.HEADER));
        if(side instanceof JComponent sidebar)parts.add(new dev.synesis.poc.ui.LibraryDeparture.Part(sidebar,dev.synesis.poc.ui.LibraryDeparture.Kind.SIDEBAR));
        return parts;
    }

    private void showPlannerSection() {
        if(plannerSection&&!sectionMotion.active()){showPlannerNow();return;}
        sectionMotion.change(this::showPlannerNow,false);
    }
    private void showPlannerNow() {
        plannerSection=true;
        profileSection=false;
        mainCards.show(mainViews,"planner");
        libraryContent.repaint();
    }

    private void showLibrarySection(boolean recent) {
        if(plannerSection||profileSection||sectionMotion.active())sectionMotion.change(()->showLibraryNow(recent),true);
        else showLibraryNow(recent);
    }
    private void showLibraryNow(boolean recent) {
        replayItems=true;
        plannerSection=false;
        profileSection=false;
        recentSection=recent;
        if(recent)recentFirst=true;
        currentFolderId="";
        mainCards.show(mainViews,"documents");
        showItems();
        scroll.getVerticalScrollBar().setValue(0);
        libraryContent.repaint();
    }

    private void showProfileSection() {
        if(profileSection&&!sectionMotion.active()){showProfileNow();return;}
        sectionMotion.change(this::showProfileNow,false);
    }
    private void showProfileNow() {
        plannerSection=false;
        profileSection=true;
        mainCards.show(mainViews,"profile");
        libraryContent.repaint();
        refreshProfile();
    }

    private JPanel profilePanel() {
        JPanel details=profileUsagePanel();
        JButton usage=new JButton("사용 내역 보기");
        usage.addActionListener(event->{
            details.setPreferredSize(new Dimension(820,600));
            JOptionPane.showMessageDialog(this,details,"내 사용 내역",JOptionPane.PLAIN_MESSAGE);
        });
        JButton logout=new JButton("로그아웃");
        logout.addActionListener(event ->
            dev.synesis.poc.ui.LoginTransition.playLogout(logout, () -> logoutHandler.run()));
        JComponent surface=dev.synesis.poc.ui.ProfileDesign.create(profilePlan,profileNextPaymentAt,
            profileRemainingCredits,profilePlanState,profileCreditProgress,profileCreditSummary,
            rechargeCredits,usage,logout);
        JPanel panel=new JPanel(new BorderLayout());panel.setBackground(Color.WHITE);
        JScrollPane scroller=new dev.synesis.poc.ui.FadeScrollPane(surface);
        scroller.setBorder(null);scroller.getViewport().setBackground(Color.WHITE);
        scroller.setHorizontalScrollBarPolicy(ScrollPaneConstants.HORIZONTAL_SCROLLBAR_NEVER);
        scroller.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
        panel.add(scroller,BorderLayout.CENTER);
        return panel;
    }

    private JPanel profileUsagePanel() {
        JPanel panel=new JPanel(new BorderLayout());panel.setBackground(StudyTheme.CANVAS);
        JPanel content=new JPanel();content.setBackground(StudyTheme.CANVAS);
        content.setLayout(new BoxLayout(content,BoxLayout.Y_AXIS));
        content.setBorder(new EmptyBorder(34,36,36,36));
        JLabel title=new JLabel("내 정보");title.setFont(StudyTheme.font(Font.BOLD,24));
        title.setForeground(StudyTheme.INK);title.setAlignmentX(Component.LEFT_ALIGNMENT);
        content.add(title);
        content.add(Box.createVerticalStrut(9));
        JLabel subtitle=profileSubtitle;
        subtitle.setFont(StudyTheme.font(Font.PLAIN,13));subtitle.setForeground(StudyTheme.MUTED);
        subtitle.setAlignmentX(Component.LEFT_ALIGNMENT);content.add(subtitle);
        content.add(Box.createVerticalStrut(30));
        content.add(profileMetric("현재 플랜",profilePlan));
        content.add(Box.createVerticalStrut(14));
        JPanel billing=StudyTheme.panel(14,StudyTheme.PAPER);
        billing.setLayout(new BoxLayout(billing,BoxLayout.Y_AXIS));
        billing.setBorder(new EmptyBorder(18,24,18,24));
        billing.setAlignmentX(Component.LEFT_ALIGNMENT);
        billing.setMaximumSize(new Dimension(Integer.MAX_VALUE,130));
        for(JLabel field:List.of(profilePurchasedAt,profileNextPaymentAt,profileAutoRenew)) {
            field.setFont(StudyTheme.font(Font.PLAIN,13));field.setForeground(StudyTheme.INK);
            field.setAlignmentX(Component.LEFT_ALIGNMENT);billing.add(field);billing.add(Box.createVerticalStrut(8));
        }
        content.add(billing);content.add(Box.createVerticalStrut(14));
        JPanel walletCard=profileMetric("잔여 크레딧",profileRemainingCredits);
        JPanel walletRow=new JPanel(new BorderLayout(20,0));walletRow.setOpaque(false);
        walletCard.remove(profileRemainingCredits);
        walletRow.add(profileRemainingCredits,BorderLayout.CENTER);
        StudyTheme.button(rechargeCredits,true);
        rechargeCredits.setEnabled(false);
        profilePlan.setText("확인 중…");profilePurchasedAt.setText("최근 플랜 결제일: —");
        profileNextPaymentAt.setText("다음 결제 예정일: —");profileAutoRenew.setText("자동결제: —");
        rechargeCredits.addActionListener(event -> CreditTopUpDialog.open(this,root,creditSnapshot,loader,()->refreshProfile()));
        walletRow.add(rechargeCredits,BorderLayout.EAST);
        walletRow.setAlignmentX(Component.LEFT_ALIGNMENT);walletCard.add(walletRow);
        content.add(walletCard);
        content.add(Box.createVerticalStrut(14));
        content.add(profileMetric("총 사용 크레딧",profileUsedCredits));
        content.add(Box.createVerticalStrut(14));
        content.add(profileMetric("PDF당 평균 · 전체 누적 기준",profileAverageCredits));
        content.add(Box.createVerticalStrut(14));
        content.add(profileMetric("총 사용 토큰",profileTokens));
        content.add(Box.createVerticalStrut(14));
        content.add(profileMetric("사용량 기준 달러 가치",profileCost));
        content.add(Box.createVerticalStrut(14));
        content.add(profileMetric("현재 업로드한 PDF",profilePdfCount));
        content.add(Box.createVerticalStrut(20));
        profileDetail.setFont(StudyTheme.font(Font.PLAIN,12));profileDetail.setForeground(StudyTheme.MUTED);
        profileDetail.setAlignmentX(Component.LEFT_ALIGNMENT);content.add(profileDetail);
        content.add(Box.createVerticalStrut(8));
        JLabel estimateNote=new JLabel("API 반환 사용량과 모델 단가로 계산한 값이며, 실제 청구액과 다를 수 있어요.");
        estimateNote.setFont(StudyTheme.font(Font.PLAIN,11));estimateNote.setForeground(StudyTheme.MUTED);
        estimateNote.setAlignmentX(Component.LEFT_ALIGNMENT);content.add(estimateNote);
        content.add(Box.createVerticalStrut(10));
        profileWalletDetail.setFont(StudyTheme.font(Font.PLAIN,11));
        profileWalletDetail.setForeground(StudyTheme.MUTED);profileWalletDetail.setAlignmentX(Component.LEFT_ALIGNMENT);
        content.add(profileWalletDetail);
        content.add(Box.createVerticalStrut(32));
        JButton logout=new JButton("로그아웃");
        StudyTheme.button(logout,false);
        logout.setAlignmentX(Component.LEFT_ALIGNMENT);
        logout.addActionListener(event ->
            dev.synesis.poc.ui.LoginTransition.playLogout(logout, () -> logoutHandler.run()));
        JPanel actions=new JPanel(new FlowLayout(FlowLayout.LEFT,10,0));actions.setOpaque(false);
        actions.setAlignmentX(Component.LEFT_ALIGNMENT);
        StudyTheme.button(resetStatistics,false);
        resetStatistics.setToolTipText("토큰·비용·사용 크레딧 집계를 지금부터 다시 시작해요. 잔여 크레딧도 0으로 초기화해요. 현재 플랜과 결제 예정 정보도 초기화해요. PDF당 평균은 전체 기록을 유지해요.");
        resetStatistics.addActionListener(event -> resetProfileStatistics());
        JButton subscriptionUsage=new JButton("내 구독 사용량");StudyTheme.button(subscriptionUsage,false);
        subscriptionUsage.addActionListener(event->{
            subscriptionUsage.setEnabled(false);
            loader.execute(()->{
                String report;
                try {report=SubscriptionUsage.report(root);}catch(Exception failure) {report="사용량을 읽지 못했어요: "+failure.getMessage();}
                String message=report;
                SwingUtilities.invokeLater(()->{subscriptionUsage.setEnabled(true);
                    JOptionPane.showMessageDialog(this,new JLabel(message),"내 구독 사용량",JOptionPane.PLAIN_MESSAGE);refreshProfile();});
            });
        });
        actions.add(subscriptionUsage);actions.add(logout);actions.add(resetStatistics);content.add(actions);
        JScrollPane scroller=new dev.synesis.poc.ui.FadeScrollPane(content);
        scroller.setBorder(null);scroller.getViewport().setBackground(StudyTheme.CANVAS);
        scroller.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
        panel.add(scroller,BorderLayout.CENTER);
        return panel;
    }

    private static JPanel profileMetric(String name,JLabel value) {
        JPanel card=StudyTheme.panel(14,StudyTheme.PAPER);
        card.setLayout(new BoxLayout(card,BoxLayout.Y_AXIS));
        card.setBorder(new EmptyBorder(20,24,22,24));
        card.setAlignmentX(Component.LEFT_ALIGNMENT);
        card.setMaximumSize(new Dimension(Integer.MAX_VALUE,110));
        JLabel title=new JLabel(name);title.setForeground(StudyTheme.MUTED);
        title.setFont(StudyTheme.font(Font.PLAIN,12));
        title.setAlignmentX(Component.LEFT_ALIGNMENT);card.add(title);
        card.add(Box.createVerticalStrut(12));
        value.setForeground(StudyTheme.INK);value.setFont(StudyTheme.font(Font.BOLD,23));
        value.setAlignmentX(Component.LEFT_ALIGNMENT);card.add(value);
        return card;
    }

    private void resetProfileStatistics() {
        if(resettingStatistics)return;
        resettingStatistics=true;resetStatistics.setEnabled(false);rechargeCredits.setEnabled(false);
        ++profileRevision;
        profileDetail.setText("사용량 집계를 초기화하고 있어요…");
        List<PdfLibraryStore.Item> current=List.copyOf(items);
        loader.execute(() -> {
            String error=null;
            try {
                java.time.Instant since=ProfileUsagePeriod.since(root);
                PdfUsageStore.Totals totals=PdfUsageStore.read(root,current,since);
                if(totals.unreadableFiles()>0)throw new IOException("읽지 못한 사용량 기록이 있어 초기화를 중단했어요.");
                // Persist first-generation identities before changing the display period.
                PdfFirstGenerationStats.read(root,current,since);
                CreditWallet.restartStatistics(root,totals.usd(),java.time.Instant.now());
            } catch(Exception failure) {error=failure.getMessage();}
            String message=error;
            SwingUtilities.invokeLater(() -> {
                resettingStatistics=false;resetStatistics.setEnabled(true);refreshProfile();
                if(message!=null)JOptionPane.showMessageDialog(this,message,"초기화 확인",JOptionPane.ERROR_MESSAGE);
            });
        });
    }

    static String pdfAverageHtml(SubscriptionUsage.Snapshot usage) {
        return CreditWallet.displayHtml(usage.averagePdfCredits()).replace("</html>",String.format(Locale.KOREA,
            "<span style='font-size:12pt;color:#6d7785'> · 원가 약 %,.2f원 · %d회 생성 평균</span></html>",
            usage.averagePdfKrw(),usage.summaryCount()));
    }

    private void refreshProfile() {
        int token=++profileRevision;
        profileTokens.setText("계산 중…");profileCost.setText("계산 중…");
        profileUsedCredits.setText("계산 중…");profileRemainingCredits.setText("계산 중…");
        profileAverageCredits.setText("계산 중…");
        rechargeCredits.setEnabled(false);
        resetStatistics.setEnabled(!resettingStatistics);
        profilePdfCount.setText(String.format(Locale.KOREA,"%,d개",items.size()));
        profileDetail.setText("사용량을 읽고 있어요…");
        List<PdfLibraryStore.Item> current=List.copyOf(items);
        loader.execute(() -> {
            java.time.Instant since;
            try {since=ProfileUsagePeriod.since(root);}
            catch(IOException failure) {
                SwingUtilities.invokeLater(()->{if(token==profileRevision)profileDetail.setText(failure.getMessage());});return;
            }
            PdfUsageStore.Totals totals=PdfUsageStore.read(root,current,since);
            SubscriptionUsage.Snapshot average=null;
            try {SubscriptionUsage.activate(root);average=PdfLifetimeAverage.read(root);}
            catch(Exception failure) { /* Keep usage available while flagging an unavailable average. */ }
            SubscriptionUsage.Snapshot loadedAverage=average;
            CreditWallet.Snapshot wallet=null;String walletError=null;
            try {
                if(totals.unreadableFiles()>0)throw new IOException("사용량 기록을 모두 읽은 뒤 충전할 수 있어요.");
                wallet=CreditWallet.read(root,totals.usd());
            } catch(IOException failure) {walletError=failure.getMessage();}
            CreditWallet.Snapshot loadedWallet=wallet;String loadedWalletError=walletError;
            SwingUtilities.invokeLater(() -> {
                if(token!=profileRevision || !profileSection)return;
                String period=DateTimeFormatter.ofPattern("yyyy.MM.dd HH:mm:ss").withZone(ZoneId.of("Asia/Seoul")).format(since);
                profileSubtitle.setText(period+" 이후의 PDF 학습·AI멘토 사용량이에요.");
                profileTokens.setText(String.format(Locale.KOREA,"%,d 토큰",totals.tokens()));
                profileUsedCredits.setText(CreditWallet.displayHtml(CreditWallet.credits(totals.usd())));
                if(loadedAverage==null)profileAverageCredits.setText("평균 기록 확인 필요");
                else profileAverageCredits.setText(pdfAverageHtml(loadedAverage));
                profileAverageCredits.setToolTipText("전체 기간 AI 요약/개념 생성 총 크레딧 ÷ 생성 횟수 · 플랜 변경·통계 표시 기간과 무관 · 재생성·부분 생성 포함 · 1크레딧 원가 2.3원");
                creditSnapshot=loadedWallet;
                if(loadedWallet!=null) {
                    DateTimeFormatter billingDate=DateTimeFormatter.ofPattern("yyyy.MM.dd HH:mm").withZone(ZoneId.of("Asia/Seoul"));
                    profilePlan.setText(loadedWallet.hasActivePlan()?loadedWallet.activePlan():
                        loadedWallet.planExpiresAt()!=null?loadedWallet.activePlan()+" · 이용 기간 종료":"플랜 없음");
                    profilePurchasedAt.setText("최근 플랜 결제일: "+(loadedWallet.planPurchasedAt()==null?"—":billingDate.format(loadedWallet.planPurchasedAt())));
                    profileNextPaymentAt.setText("다음 결제 예정일: "+(loadedWallet.autoRenew() && loadedWallet.planExpiresAt()!=null
                        ?billingDate.format(loadedWallet.planExpiresAt())+" (모의)":"—"));
                    profileAutoRenew.setText(loadedWallet.autoRenew()?"자동결제: 설정됨 · 개발자 모의 설정, 실제 청구 없음":"자동결제: 설정 안 됨");
                    profileRemainingCredits.setText(CreditWallet.display(loadedWallet.balance()));
                    profileRemainingCredits.setToolTipText("남은 크레딧");
                    profilePlanState.setText(loadedWallet.hasActivePlan()?"이용 중":"미이용");
                    double granted=loadedWallet.balance().add(loadedWallet.usedSinceStart()).doubleValue();
                    profileCreditProgress.setValue(granted>0?(int)Math.round(1000*Math.max(0,Math.min(1,loadedWallet.balance().doubleValue()/granted))):0);
                    profileCreditSummary.setText(CreditWallet.display(loadedWallet.usedSinceStart())+" 크레딧 사용");
                    profileUsedCredits.setText(CreditWallet.displayHtml(loadedWallet.usedSinceStart()));
                    rechargeCredits.setEnabled(!resettingStatistics);
                    profileWalletDetail.setText("개발자 모드 · 실제 결제 없음 · 원가 2.3원 = 1크레딧 · 초기화 시 통계·잔액·플랜 초기화"
                        +(loadedWallet.hasActivePlan()?" · "+loadedWallet.activePlan()+" 이용 중":" · 플랜 없음")
                        +(loadedWallet.balance().signum()<0?" · 잔액 부족 · 유료 요약 생성 제한":""));
                } else {
                    profilePlan.setText("확인 필요");profilePlanState.setText("확인 필요");
                    profileCreditProgress.setValue(0);profileCreditSummary.setText("크레딧 기록 확인 필요");
                    profileRemainingCredits.setText("확인 필요");profileWalletDetail.setText(loadedWalletError);
                }
                double shownUsd=Math.round(totals.usd()*1_000_000d)/1_000_000d;
                profileCost.setText(String.format(Locale.KOREA,"$%.6f × 1,400 = 약 %,.2f원",
                    shownUsd,shownUsd*1400));
                String detail=String.format(Locale.KOREA,"입력 %,d · 출력 %,d 토큰",totals.inputTokens(),totals.outputTokens());
                if(totals.unknownRequests()>0)detail+=String.format(Locale.ROOT,
                    " · 사용량 미확인 %d건 (예약 $%.6f 별도)",
                    totals.unknownRequests(),totals.uncertainReservedUsd());
                if(totals.unreadableFiles()>0)detail+=" · 읽지 못한 기록 "+totals.unreadableFiles()+"개";
                profileDetail.setText(detail);
                profileDetail.setToolTipText(period+" KST 이후 요청만 집계해요. 시각이 없는 과거 기록은 파일 생성 시각을 사용해요.");
            });
        });
    }

    public void refresh() {
        int token = ++revision;
        loader.execute(() -> {
            List<PdfLibraryStore.Item> found;
            try { found = PdfLibraryStore.list(root); }
            catch (Exception error) { found = List.of(); }
            PdfLibraryOrganization folders=null;
            try {
                folders=PdfLibraryOrganization.load(root);
                folders.ensureTrashFolder();
                for(PdfLibraryStore.Item item:found) {
                    String destination=pendingImports.remove(item.id());
                    if(destination!=null && folders.location(item.id()).isEmpty())
                        folders.moveDocument(item.id(),destination);
                }
            } catch(IOException error) {
                SwingUtilities.invokeLater(() -> JOptionPane.showMessageDialog(this,
                    "폴더 목록을 읽지 못했어요.\n"+error.getMessage(),"내 문서",JOptionPane.ERROR_MESSAGE));
            }
            List<PdfLibraryStore.Item> ready = found;
            PdfLibraryOrganization readyFolders=folders;
            SwingUtilities.invokeLater(() -> {
                if (token != revision) return;
                items = ready;
                if(readyFolders!=null)organization=readyFolders;
                Set<String> available=new HashSet<>();
                for(PdfLibraryStore.Item item:items)available.add(item.id());
                thumbnails.keySet().retainAll(available);thumbnailCache.keySet().retainAll(available);
                selectedIds.retainAll(available);
                if(organization!=null)selectedFolderIds.retainAll(organization.folders().stream().map(PdfLibraryOrganization.Folder::id).toList());
                if(organization!=null&&!currentFolderId.isEmpty()&&organization.folder(currentFolderId)==null)currentFolderId="";
                showItems();
                if(profileSection)refreshProfile();
            });
            for (PdfLibraryStore.Item item : found) {
                if (token != revision) return;
                ImageIcon icon = cover(item);
                SwingUtilities.invokeLater(() -> {
                    if (token != revision) return;
                    if(icon!=null)thumbnails.put(item.id(), icon);
                    JLabel target = covers.get(item.id());
                    if (target != null && icon!=null) { target.setText(""); target.setIcon(icon); }
                    JLabel pages=pageCountLabels.get(item.id());
                    if(pages!=null)pages.setText(Boolean.TRUE.equals(pages.getClientProperty("library.gridMetadata"))?gridPageCount(item.id()):pageCountText(item.id()));
                });
            }
        });
    }

    private boolean isTrashView(){return organization!=null&&organization.isFolderInTrash(currentFolderId);}
    private boolean visibleDocument(PdfLibraryStore.Item item){
        if(!matchesSearch(item))return false;
        if(organization==null)return true;
        return recentSection?!organization.isDocumentInTrash(item.id()):organization.location(item.id()).equals(currentFolderId);
    }
    private boolean visibleFolder(PdfLibraryOrganization.Folder folder){
        return folder.parentId().equals(currentFolderId)&&folder.name().toLowerCase(Locale.ROOT)
            .contains(search.getText().strip().toLowerCase(Locale.ROOT));
    }
    private void openOrSelectFolder(PdfLibraryOrganization.Folder folder){
        if(selectionMode&&!PdfLibraryOrganization.isTrash(folder.id())){
            if(!selectedFolderIds.add(folder.id()))selectedFolderIds.remove(folder.id());showItems();
        }else enterFolder(folder.id());
    }

    private void showItems() {
        searchDelay.stop();
        clearMoveHint();
        Map<String,dev.synesis.poc.ui.LibraryItemMotion.Entrance> previousFolders=new HashMap<>(),previousDocuments=new HashMap<>();
        folderCards.forEach((id,card)->previousFolders.put(id,((AnimatedCard)card).entranceState()));
        documentCards.forEach((id,card)->previousDocuments.put(id,((AnimatedCard)card).entranceState()));
        grid.removeAll(); covers.clear();folderIcons.clear();folderCards.clear();documentCards.clear();pageCountLabels.clear();
        setColumns();
        if(listView)grid.add(listHeader());
        showBreadcrumbs();
        if(selectionMode && activeDocumentDrag==null) {
            Set<String> visible=new HashSet<>();
            for(PdfLibraryStore.Item item:items)if(visibleDocument(item))visible.add(item.id());
            selectedIds.retainAll(visible);
            Set<String> visibleFolders=new HashSet<>();
            if(!recentSection&&organization!=null)for(var folder:organization.folders())if(visibleFolder(folder))visibleFolders.add(folder.id());
            selectedFolderIds.retainAll(visibleFolders);
        }
        List<PdfLibraryStore.Item> visible=new ArrayList<>(items);
        if(recentFirst)visible.sort(Comparator.comparing(PdfLibraryStore.Item::lastOpenedAt).reversed());
        else visible.sort(Comparator.comparing(PdfLibraryStore.Item::name,String.CASE_INSENSITIVE_ORDER));
        int count=0;
        pendingImportKey=pendingImportKey();
        if(!recentSection&&currentFolderId.isEmpty())for(var pending:pendingImportCards()) {
            if(!pending.name().toLowerCase(Locale.ROOT).contains(search.getText().strip().toLowerCase(Locale.ROOT)))continue;
            grid.add(importPlaceholder(pending));count++;
        }
        if(!recentSection && organization!=null)for(PdfLibraryOrganization.Folder folder:organization.folders())
            if(visibleFolder(folder)) {
                grid.add(listView?folderRow(folder):folderCard(folder));count++;
            }
        for (PdfLibraryStore.Item item : visible)
            if(visibleDocument(item)) {
                grid.add(listView?documentRow(item):documentCard(item));count++;
            }
        int entranceOrder=0;
        for(var entry:folderCards.entrySet()) {
            AnimatedCard card=(AnimatedCard)entry.getValue();
            if(activeDocumentDrag!=null)card.restoreEntrance(null);
            else if(replayItems||!previousFolders.containsKey(entry.getKey()))card.entrance(0,true);
            else card.restoreEntrance(previousFolders.get(entry.getKey()));
            card.installHover();
        }
        for(var entry:documentCards.entrySet()) {
            AnimatedCard card=(AnimatedCard)entry.getValue();
            if(activeDocumentDrag!=null)card.restoreEntrance(null);
            else if(replayItems||!previousDocuments.containsKey(entry.getKey()))card.entrance(0,true);
            else card.restoreEntrance(previousDocuments.get(entry.getKey()));
            card.installHover();
        }
        for(Component component:grid.getComponents())if(component instanceof AnimatedCard card)card.order(entranceOrder++);
        replayItems=false;
        sectionCount.setText(count+"개 항목");
        emptyFolderState.setVisible(!recentSection && !currentFolderId.isEmpty()
            && search.getText().isBlank() && count==0);
        updateSelectionControls();
        setColumns(); grid.revalidate(); grid.repaint();libraryContent.repaint();
    }

    private boolean matchesSearch(PdfLibraryStore.Item item) {
        String query=search.getText().strip().toLowerCase(Locale.ROOT);
        return query.isEmpty() || item.name().toLowerCase(Locale.ROOT).contains(query);
    }

    /** Native buttons and a static surface; wrapping only recalculates when the width changes. */
    private static final class BulkSelectionBar extends JPanel {
        private int lastWidth=-1;
        BulkSelectionBar() {
            super(new FlowLayout(FlowLayout.LEFT,8,8));setOpaque(false);
            setBorder(new EmptyBorder(18,49,10,49));
            addComponentListener(new java.awt.event.ComponentAdapter(){
                @Override public void componentResized(java.awt.event.ComponentEvent event){
                    if(lastWidth!=getWidth()){lastWidth=getWidth();invalidate();revalidate();}
                }
            });
        }
        @Override public Dimension getPreferredSize() {
            int width=getWidth()>0?getWidth():getParent()!=null&&getParent().getWidth()>0?getParent().getWidth():1000;
            Insets insets=getInsets();int available=Math.max(1,width-insets.left-insets.right-16);
            int rowWidth=0,rowHeight=0,height=insets.top+insets.bottom+16;
            for(Component child:getComponents())if(child.isVisible()) {
                Dimension size=child.getPreferredSize();
                if(rowWidth>0&&rowWidth+8+size.width>available){height+=rowHeight+8;rowWidth=0;rowHeight=0;}
                rowWidth+=(rowWidth==0?0:8)+size.width;rowHeight=Math.max(rowHeight,size.height);
            }
            return new Dimension(width,height+rowHeight);
        }
        @Override public Dimension getMinimumSize(){return new Dimension(0,getPreferredSize().height);}
        @Override public Dimension getMaximumSize(){return new Dimension(Integer.MAX_VALUE,getPreferredSize().height);}
        @Override protected void paintComponent(Graphics graphics) {
            super.paintComponent(graphics);Graphics2D g=(Graphics2D)graphics.create();
            try {
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(new Color(0xf7f7f7));g.fillRoundRect(37,8,Math.max(0,getWidth()-74),Math.max(0,getHeight()-9),16,16);
                g.setColor(BORDER);g.drawRoundRect(37,8,Math.max(0,getWidth()-75),Math.max(0,getHeight()-10),16,16);
            } finally {g.dispose();}
        }
    }

    /** Called on the EDT only after an item operation has completed successfully. */
    private void completeSelectionAction() {
        selectionMode=false;
        selectedIds.clear();selectedFolderIds.clear();
        updateSelectionControls();
    }

    private void updateSelectionControls() {
        selectionToggle.setText(selectionMode?"선택 종료":"일괄 선택");
        selectionToggle.setSelected(selectionMode);
        selectionToggle.setBackground(selectionMode?new Color(0x2563eb):Color.WHITE);
        selectionToggle.setForeground(selectionMode?Color.WHITE:LibraryDesign.INK);
        selectionToggle.repaint();
        bulkBar.setVisible(selectionMode);
        selectedCount.setText((selectedIds.size()+selectedFolderIds.size())+"개 선택");
        boolean hasSelection=!selectedIds.isEmpty()||!selectedFolderIds.isEmpty();
        deleteSelectedFiles.setText(isTrashView()?"영구 삭제하기":"휴지통으로 이동시키기");
        restoreSelected.setVisible(isTrashView());restoreSelected.setEnabled(hasSelection&&isTrashView());
        clearSelection.setEnabled(hasSelection);
        deleteSelectedFiles.setEnabled(hasSelection);
        deleteSelectedData.setEnabled(!selectedIds.isEmpty()||!selectedFolderIds.isEmpty());
        revalidate();
    }

    private void setColumns() {
        if(listView){if(!(grid.getLayout() instanceof BoxLayout))grid.setLayout(new BoxLayout(grid,BoxLayout.Y_AXIS));grid.revalidate();return;}
        int width = scroll.getViewport().getWidth();
        if(width<=0)width=Math.max(320,getWidth()-LibraryDesign.SIDEBAR_WIDTH);
        int columns = Math.max(1, Math.min(8, (width - 74 + 24) / 268));
        if (!(grid.getLayout() instanceof GridLayout layout) || layout.getColumns() != columns) {
            grid.setLayout(new GridLayout(0, columns, 24, 28));
            // The shelf's BoxLayout caches row heights. Drop that cache when wrapping changes.
            if(grid.getParent()!=null)grid.getParent().invalidate();
            shelf.invalidate();shelf.revalidate();
        }
        grid.revalidate();
    }

    /** Only transient, bounded sprites are retained between prepare and commit. */
    private record AssistantMoveVisual(String id,boolean folder,BufferedImage image,Point from){}
    private record AssistantMoveTicket(String originFolder,List<AssistantMoveVisual> visuals){}
    private final class AssistantUi implements AssistantLibraryUi {
        private final Set<CompletableFuture<JsonObject>> pending=new HashSet<>();
        private final Set<javax.swing.Timer> timers=new HashSet<>();
        private boolean closed;
        private <T>T onEdt(java.util.concurrent.Callable<T> action)throws Exception{
            if(SwingUtilities.isEventDispatchThread())return action.call();
            java.util.concurrent.FutureTask<T> task=new java.util.concurrent.FutureTask<>(action);
            SwingUtilities.invokeAndWait(task);
            try{return task.get();}catch(java.util.concurrent.ExecutionException failure){
                if(failure.getCause() instanceof Exception error)throw error;throw failure;
            }
        }
        private CompletableFuture<JsonObject> dispatch(java.util.function.Consumer<CompletableFuture<JsonObject>> action){
            CompletableFuture<JsonObject> result=new CompletableFuture<>();
            SwingUtilities.invokeLater(()->{
                if(closed){result.completeExceptionally(new IOException("자료 화면이 닫혔어요."));return;}
                pending.add(result);
                try{action.accept(result);}catch(Exception failure){result.completeExceptionally(failure);}
                result.whenComplete((value,failure)->SwingUtilities.invokeLater(()->pending.remove(result)));
            });
            return result;
        }
        private JsonObject result(String status,String id){JsonObject out=new JsonObject();out.addProperty("status",status);out.addProperty("id",id);return out;}
        private void ready()throws IOException{if(closed||organization==null)throw new IOException("자료 목록을 읽는 중이에요. 잠시 뒤 다시 요청해 주세요.");}
        private String folderPath(String id){
            StringBuilder path=new StringBuilder("홈화면");
            if(organization!=null)for(PdfLibraryOrganization.Folder folder:organization.path(id))path.append(" > ").append(folder.name());
            return path.toString();
        }
        @Override public JsonObject viewContext()throws Exception{return onEdt(()->{
            ready();if(searchDelay.isRunning())showItems();JsonObject out=new JsonObject();
            boolean library=isShowing()&&!plannerSection&&!profileSection;
            out.addProperty("screen",!isShowing()?"other":plannerSection?"planner":profileSection?"profile":recentSection?"recent":"library");
            out.add("section",out.get("screen"));
            out.addProperty("libraryVisible",library);out.addProperty("currentFolderId",currentFolderId);out.addProperty("currentPath",folderPath(currentFolderId));
            out.addProperty("search",search.getText());out.addProperty("recentSection",recentSection);
            JsonArray visible=new JsonArray();
            if(library){
                for(String id:folderCards.keySet()){JsonObject item=new JsonObject();item.addProperty("kind","folder");item.addProperty("id",id);visible.add(item);}
                for(String id:documentCards.keySet()){JsonObject item=new JsonObject();item.addProperty("kind","document");item.addProperty("id",id);visible.add(item);}
            }
            out.add("visibleItems",visible);
            List<String> visibleIds=new ArrayList<>();folderCards.keySet().forEach(id->visibleIds.add("f:"+id));documentCards.keySet().forEach(id->visibleIds.add("d:"+id));Collections.sort(visibleIds);
            out.addProperty("viewRevision",Integer.toHexString(Objects.hash(revision,currentFolderId,recentSection,plannerSection,profileSection,isShowing(),search.getText(),visibleIds)));
            return out;
        });}
        private void switchFolder(String id,Runnable after)throws IOException{
            ready();if(!id.isEmpty()&&organization.folder(id)==null)throw new IOException("폴더를 찾지 못했어요. 목록을 다시 확인해 주세요.");
            // An explicit assistant destination must survive an in-flight sidebar
            // animation. Its replaceable callback is presentation, not the task.
            sectionMotion.cancel();
            Runnable change=()->{
                if(closed)return;
                plannerSection=false;profileSection=false;recentSection=false;
                mainCards.show(mainViews,"documents");search.setText("");enterFolder(id);libraryContent.repaint();after.run();
            };
            change.run();
        }
        @Override public java.util.concurrent.CompletionStage<JsonObject> navigateFolder(String id){return dispatch(future->{
            try{
                ready();
                if(id.equals(currentFolderId)&&!recentSection&&!plannerSection&&!profileSection&&!sectionMotion.active()){
                    future.complete(result("already_open",id));return;
                }
                switchFolder(id,()->future.complete(result("opened",id)));
            }catch(Exception failure){future.completeExceptionally(failure);}
        });}
        @Override public java.util.concurrent.CompletionStage<JsonObject> openDocument(String id){return dispatch(future->{
            try{
                ready();PdfLibraryStore.Item item=items.stream().filter(candidate->candidate.id().equals(id)).findFirst().orElseThrow(()->new IOException("문서를 찾지 못했어요. 목록을 다시 확인해 주세요."));
                String destination=organization.location(id);
                boolean changed=!currentFolderId.equals(destination)||recentSection||plannerSection||profileSection;
                Runnable openCard=()->{
                    if(closed||future.isDone())return;
                    try{
                        if(!Files.isRegularFile(item.source(),java.nio.file.LinkOption.NOFOLLOW_LINKS))throw new IOException("열려는 원본 파일이 없어 요청을 멈췄어요.");
                        Runnable openRequested=()->{
                            if(closed||future.isDone())return;
                            try{open.accept(item.source());future.complete(result("opened",id));}catch(Exception failure){future.completeExceptionally(failure);}
                        };
                        // Keep the requested document even if the user navigates or
                        // filters the shelf during the presentation pause.
                        if(!currentFolderId.equals(destination)||plannerSection||profileSection||!isShowing()){
                            openRequested.run();return;
                        }
                        JPanel card=documentCards.get(id);
                        if(card==null||card instanceof AnimatedCard animated&&animated.timer!=null&&animated.timer.isRunning()){
                            openRequested.run();return;
                        }
                        if(selectionMode){selectionMode=false;selectedIds.clear();selectedFolderIds.clear();showItems();card=documentCards.get(id);}
                        if(card==null){openRequested.run();return;}
                        card.scrollRectToVisible(new Rectangle(card.getSize()));
                        animateOpen(card,openRequested);
                    }catch(Exception failure){future.completeExceptionally(failure);}
                };
                if(changed)switchFolder(destination,()->later(200,openCard));
                else{if(!search.getText().isEmpty()){search.setText("");showItems();}SwingUtilities.invokeLater(openCard);}
            }catch(Exception failure){future.completeExceptionally(failure);}
        });}
        private void later(int delay,Runnable action){
            javax.swing.Timer timer=new javax.swing.Timer(delay,null);timer.setRepeats(false);
            timer.addActionListener(event->{timers.remove(timer);if(!closed)action.run();});timers.add(timer);timer.start();
        }
        @Override public Object prepareMutation(JsonArray changes)throws Exception{return onEdt(()->{
            ready();List<AssistantMoveVisual> visuals=new ArrayList<>();
            if(isShowing()&&!plannerSection&&!profileSection){
                for(JsonElement element:changes){JsonObject change=element.getAsJsonObject();
                    if(!change.has("operation")||!Set.of("move","trash").contains(change.get("operation").getAsString()))continue;
                    String id=change.get("id").getAsString();boolean folder=change.get("kind").getAsString().equals("folder");
                    JComponent artwork=folder?folderIcons.get(id):documentArtwork(id);
                    JPanel sourceCard=folder?folderCards.get(id):documentCards.get(id);
                    if(changes.size()==1&&artwork!=null)artwork.scrollRectToVisible(new Rectangle(artwork.getSize()));
                    Rectangle viewport=SwingUtilities.convertRectangle(scroll.getViewport(),new Rectangle(scroll.getViewport().getSize()),dropLayer);
                    JComponent capture=visibleSource(artwork,viewport)?artwork:visibleSource(sourceCard,viewport)?sourceCard:null;
                    if(capture==null)continue;
                    Rectangle bounds=SwingUtilities.convertRectangle(capture,new Rectangle(capture.getSize()),dropLayer);
                    Rectangle visible=bounds.intersection(viewport);
                    // A partially visible paper can have its center outside the viewport.
                    // Launch from its visible pixels rather than silently dropping the effect.
                    Point from=new Point((int)visible.getCenterX(),(int)visible.getCenterY());
                    visuals.add(new AssistantMoveVisual(id,folder,LibraryDragPreview.capture(capture),from));
                    if(visuals.size()>=LibrarySelectionDrag.MAX_SPRITES)break;
                }
            }
            return new AssistantMoveTicket(currentFolderId,List.copyOf(visuals));
        });}
        private boolean visibleSource(JComponent source,Rectangle viewport){
            return source!=null&&source.isShowing()&&source.getWidth()>0&&source.getHeight()>0
                &&SwingUtilities.convertRectangle(source,new Rectangle(source.getSize()),dropLayer).intersects(viewport);
        }
        private boolean visibleTarget(JComponent target){
            if(target==null||!target.isShowing()||target.getWidth()<=0||target.getHeight()<=0)return false;
            if(!SwingUtilities.isDescendingFrom(target,grid))return true;
            Point center=SwingUtilities.convertPoint(target,target.getWidth()/2,target.getHeight()/2,scroll.getViewport());
            return new Rectangle(scroll.getViewport().getSize()).contains(center);
        }
        private JComponent nearestTarget(String destination){
            JComponent exact=folderIcons.get(destination);if(visibleTarget(exact))return exact;
            List<PdfLibraryOrganization.Folder> targetPath=organization.path(destination);
            for(PdfLibraryOrganization.Folder ancestor:targetPath){JComponent visible=folderIcons.get(ancestor.id());if(visibleTarget(visible))return visible;}
            for(int i=targetPath.size()-1;i>=0;i--){JButton crumb=breadcrumbTargets.get(targetPath.get(i).id());if(visibleTarget(crumb))return crumb;}
            JComponent home=breadcrumbTargets.get("");return visibleTarget(home)?home:null;
        }
        private void layoutCommittedScene(Container container){
            container.doLayout();
            for(Component child:container.getComponents())if(child.isVisible()&&child instanceof Container nested)layoutCommittedScene(nested);
        }
        @Override public void cancelMutation(Object prepared){if(prepared instanceof AssistantMoveTicket ticket)release(ticket);}
        @Override public java.util.concurrent.CompletionStage<JsonObject> finishMutation(Object prepared,JsonObject committed){
            AssistantMoveTicket ticket=prepared instanceof AssistantMoveTicket value?value:new AssistantMoveTicket("",List.of());
            // Durable receipt parsing can grow with use; never read it on the event thread.
            return CompletableFuture.supplyAsync(()->{
                try{return PdfLibraryOrganization.load(root);}catch(IOException failure){throw new java.util.concurrent.CompletionException(failure);}
            }).thenCompose(loaded->dispatch(future->{
                try{
                    ready();organization=loaded;
                    // Names share the atomic organization commit. Refresh cached cards too,
                    // without re-reading PDFs or waiting for an unrelated library refresh.
                    if(committed.has("renamed")&&!committed.getAsJsonArray("renamed").isEmpty()){
                        Map<String,String> names=new HashMap<>();for(JsonElement entry:committed.getAsJsonArray("renamed")){JsonObject rename=entry.getAsJsonObject();if(rename.get("kind").getAsString().equals("document"))names.put(rename.get("id").getAsString(),rename.get("name").getAsString());}
                        items=items.stream().map(item->new PdfLibraryStore.Item(item.id(),item.source(),
                            names.getOrDefault(item.id(),loaded.documentName(item.id(),item.name())),item.addedAt(),item.lastOpenedAt())).toList();
                    }
                    boolean moving=committed.has("moved")&&!committed.getAsJsonArray("moved").isEmpty();
                    boolean created=committed.has("createdFolders")&&!committed.getAsJsonArray("createdFolders").isEmpty();
                    // Match native drop: retain source cards and breadcrumb geometry until
                    // the flight finishes. Rebuilding first removes the source and recreates
                    // the root breadcrumb with zero bounds before layout has run.
                    if(!moving||created||ticket.visuals().isEmpty()){
                        showItems();layoutCommittedScene(dropLayer);
                    }
                    committed.addProperty("animationPreparedCount",ticket.visuals().size());committed.addProperty("animatedCount",0);
                    SwingUtilities.invokeLater(()->{
                        try{
                            JsonArray moved=committed.has("moved")?committed.getAsJsonArray("moved"):new JsonArray();
                            Map<String,List<AssistantMoveVisual>> destinations=new LinkedHashMap<>();
                            for(AssistantMoveVisual visual:ticket.visuals())for(JsonElement element:moved){
                                JsonObject move=element.getAsJsonObject();if(visual.id().equals(move.get("id").getAsString())){
                                    destinations.computeIfAbsent(move.get("parentId").getAsString(),id->new ArrayList<>()).add(visual);break;
                                }
                            }
                            playMoveGroups(ticket,new ArrayList<>(destinations.entrySet()),0,committed,future);
                        }catch(Exception failure){release(ticket);future.completeExceptionally(failure);}
                    });
                }catch(Exception failure){release(ticket);future.completeExceptionally(failure);}
            })).whenComplete((value,failure)->{if(failure!=null)release(ticket);});
        }
        private void playMoveGroups(AssistantMoveTicket ticket,List<Map.Entry<String,List<AssistantMoveVisual>>> groups,int index,JsonObject committed,CompletableFuture<JsonObject> future){
            if(future.isDone()){release(ticket);return;}
            if(closed||!ticket.originFolder().equals(currentFolderId)||!isShowing()||plannerSection||profileSection){finishVisual(ticket,committed,future,"screen_changed");return;}
            if(index>=groups.size()){
                String reason=committed.has("animationSkipReason")?committed.get("animationSkipReason").getAsString():
                    groups.isEmpty()&&committed.has("moved")&&!committed.getAsJsonArray("moved").isEmpty()?"no_visible_source":"";
                finishVisual(ticket,committed,future,reason);return;
            }
            var group=groups.get(index);JComponent target=nearestTarget(group.getKey());
            if(target==null){committed.addProperty("animationSkipReason","target_not_visible");playMoveGroups(ticket,groups,index+1,committed,future);return;}
            List<AssistantMoveVisual> visuals=group.getValue();AssistantMoveVisual first=visuals.get(0);
            Point to=SwingUtilities.convertPoint(target,target.getWidth()/2,target.getHeight()/2,dropLayer);
            BufferedImage image=visuals.size()==1?first.image():LibraryDragPreview.stack(visuals.stream().map(AssistantMoveVisual::image).toList(),visuals.size());
            committed.addProperty("animatedCount",committed.get("animatedCount").getAsInt()+visuals.size());
            committed.addProperty("animationTargetId",group.getKey());
            animateFolderDrop(first.id(),first.folder(),image,first.from(),to,()->{
                if(image!=first.image())image.flush();
                playMoveGroups(ticket,groups,index+1,committed,future);
            },()->{
                if(image!=first.image())image.flush();
                finishVisual(ticket,committed,future,"interrupted");
            });
        }
        private void finishVisual(AssistantMoveTicket ticket,JsonObject committed,CompletableFuture<JsonObject> future,String skipped){
            committed.addProperty("animationCompleted",skipped.isEmpty());
            if(!skipped.isEmpty())committed.addProperty("animationSkipReason",skipped);
            if(!closed&&committed.has("moved")&&!committed.getAsJsonArray("moved").isEmpty()&&committed.get("animatedCount").getAsInt()==0)refresh();
            release(ticket);future.complete(committed);
        }
        private void release(AssistantMoveTicket ticket){ticket.visuals().forEach(v->v.image().flush());}
        private void closeUi(){closed=true;timers.forEach(javax.swing.Timer::stop);timers.clear();pending.forEach(f->f.completeExceptionally(new IOException("자료 화면이 닫혔어요.")));pending.clear();}
    }

    private void enterFolder(String folderId) {
        if(organization==null || (!folderId.isEmpty() && organization.folder(folderId)==null))return;
        currentFolderId=folderId;
        replayItems=true;
        recentSection=false;
        scroll.getVerticalScrollBar().setValue(0);
        showItems();
    }

    private void showBreadcrumbs() {
        breadcrumbs.removeAll();breadcrumbTargets.clear();
        if(recentSection || profileSection)return;
        List<PdfLibraryOrganization.Folder> path=organization==null?List.of():organization.path(currentFolderId);
        List<String> ids=new ArrayList<>();
        List<String> labels=new ArrayList<>();
        ids.add("");labels.add("홈 화면");
        for(PdfLibraryOrganization.Folder folder:path) {
            ids.add(folder.id());labels.add(folder.name());
        }
        for(int i=0;i<ids.size();i++) {
            if(ids.size()>=4 && i>0 && i<ids.size()-2) {
                if(i==1) {
                    JLabel separator=new JLabel(LibraryDesign.icon("chevron",12,12));
                    breadcrumbs.add(separator);
                    JButton ellipsis=breadcrumbButton("…",null,false);
                    JPopupMenu hidden=new JPopupMenu();
                    for(int j=1;j<ids.size()-2;j++) {
                        String destination=ids.get(j);
                        JMenuItem item=new JMenuItem(labels.get(j));
                        item.addActionListener(event -> enterFolder(destination));
                        hidden.add(item);
                    }
                    ellipsis.addActionListener(event -> hidden.show(ellipsis,0,ellipsis.getHeight()));
                    breadcrumbs.add(ellipsis);
                }
                continue;
            }
            if(i>0) {
                JLabel separator=new JLabel(LibraryDesign.icon("chevron",12,12));
                breadcrumbs.add(separator);
            }
            String destination=ids.get(i);
            PdfLibraryOrganization.Folder folder=i==0?null:organization.folder(destination);
            JButton crumb=breadcrumbButton(labels.get(i),folder,destination.equals(currentFolderId));
            crumb.addActionListener(event -> enterFolder(destination));
            installDrop(crumb,destination,true);
            breadcrumbTargets.put(destination,crumb);
            breadcrumbs.add(crumb);
        }
        if(ids.size()==1) {
            JLabel separator=new JLabel(LibraryDesign.icon("chevron",12,12));
            breadcrumbs.add(separator);
        }
        breadcrumbs.revalidate();breadcrumbs.repaint();
    }

    private JPanel folderCard(PdfLibraryOrganization.Folder folder) {
        JPanel card=baseCard();folderCards.put(folder.id(),card);
        boolean trash=PdfLibraryOrganization.isTrash(folder.id());
        Icon glyph=folder.icon().equals("folder")?null:new FolderGlyph(folder.icon(),LibraryShelfDesign.folderGlyphColor(folderColor(folder)),44);
        JLabel art=LibraryShelfDesign.artwork(trash?LibraryShelfDesign.trash():LibraryShelfDesign.folder(folderColor(folder),glyph));folderIcons.put(folder.id(),art);
        JPanel preview=new JPanel(null){@Override public void doLayout(){art.setBounds(0,0,getWidth(),getHeight());
            for(Component child:getComponents())if(child instanceof JCheckBox)child.setBounds(Math.max(0,(getWidth()-198)/2),5,24,24);}};
        preview.setOpaque(false);preview.add(art);
        if(selectionMode&&!trash){
            JCheckBox selected=new JCheckBox();selected.setOpaque(false);selected.setSelected(selectedFolderIds.contains(folder.id()));selected.setToolTipText(folder.name()+" 선택");
            selected.addActionListener(event->openOrSelectFolder(folder));preview.add(selected);preview.setComponentZOrder(selected,0);
            if(selectedFolderIds.contains(folder.id()))((StudyTheme.RoundedPanel)card).setOutline(BLUE);
        }
        long subfolders=organization.folders().stream().filter(child->child.parentId().equals(folder.id())).count();
        long pdfs=items.stream().filter(item->organization.location(item.id()).equals(folder.id())).count();
        JLabel metadata=new JLabel((trash?"휴지통 · ":"폴더 · ")+(subfolders>0?"하위 폴더 "+subfolders+"개 · ":"")+"PDF "+pdfs+"개");
        JButton menu=new JButton();menu.setToolTipText(folder.name()+" 메뉴");LibraryShelfDesign.menu(menu);
        JPopupMenu actions=folderActions(folder,card,menu);
        card.add(LibraryShelfDesign.content(preview,folder.name(),menu,metadata,folderModifiedText(folder)),BorderLayout.CENTER);
        clickable(card,()->openOrSelectFolder(folder));installContextMenu(card,actions,true);
        if(!trash)enableLibraryDrag(card,new LibraryDrag(folder.id(),true),()->LibraryDragPreview.icon(art.getIcon(),art));installDrop(card,folder.id(),true);
        return card;
    }

    private static String modifiedText(PdfLibraryStore.Item item) {
        try {return DateTimeFormatter.ofPattern("yyyy. M. d.").format(Files.getLastModifiedTime(item.source()).toInstant().atZone(ZoneId.systemDefault()))+" 수정";}
        catch(IOException e){return "";}
    }
    private String folderModifiedText(PdfLibraryOrganization.Folder folder) {
        PdfLibraryStore.Item latest=null;long newest=Long.MIN_VALUE;
        for(PdfLibraryStore.Item item:items)if(organization.location(item.id()).equals(folder.id()))try {
            long time=Files.getLastModifiedTime(item.source()).toMillis();if(time>newest){latest=item;newest=time;}
        }catch(IOException ignored){}
        return latest==null?"":modifiedText(latest);
    }
    private String gridPageCount(String id){Integer count=pageCounts.get(id);return count==null?"PDF · 확인 중":count>0?"PDF · "+count+"페이지":"PDF";}

    private static Icon libraryFolderIcon(PdfLibraryOrganization.Folder folder) {
        if(PdfLibraryOrganization.isTrash(folder.id()))return LibraryShelfDesign.trash(48);
        // Folder appearance is user data. Keep custom glyphs and selected colors.
        String name=switch(folder.icon()) {
            case "folder","chart","globe","plus","stack" -> folder.icon();
            default -> null;
        };
        if(name==null)return new FolderGlyph(folder.icon(),folderColor(folder),48);
        int width=name.equals("folder")?36:48;
        int height=name.equals("folder")?32:width;
        return LibraryDesign.coloredIcon(name,width,height,folderColor(folder));
    }

    private static Color folderColor(PdfLibraryOrganization.Folder folder) {
        try {return Color.decode(folder.color());}
        catch(RuntimeException ignored) {return StudyTheme.ACCENT_DARK;}
    }

    private JButton breadcrumbButton(String name,PdfLibraryOrganization.Folder folder,boolean current) {
        String shown=name.length()>24?name.substring(0,23)+"…":name;
        JButton button=new JButton(shown) {
            @Override protected void paintComponent(Graphics graphics) {
                boolean blink=Boolean.TRUE.equals(getClientProperty("dragBlink"));
                if(getModel().isRollover() || blink) {
                    Graphics2D g=(Graphics2D)graphics.create();
                    try {
                        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                        g.setColor(blink?StudyTheme.ACCENT_SOFT:new Color(0xf6f6f6));
                        g.fillRoundRect(0,0,getWidth(),getHeight(),8,8);
                    } finally {g.dispose();}
                }
                super.paintComponent(graphics);
            }
        };
        button.setIcon(new BlinkingFolderIcon(folder==null?LibraryDesign.icon("breadcrumb-folder",16,16)
            :PdfLibraryOrganization.isTrash(folder.id())?LibraryShelfDesign.trash(16):new FolderGlyph(folder.icon(),folderColor(folder),16)));
        button.setIconTextGap(0);
        button.setFont(LibraryDesign.font(Font.PLAIN,12));
        button.setForeground(TEXT);
        button.setContentAreaFilled(false);button.setBorderPainted(false);
        button.setFocusPainted(false);button.setRolloverEnabled(true);
        button.setBorder(new EmptyBorder(4,0,4,0));
        button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        button.setToolTipText(name);
        return button;
    }

    private void renameFolder(PdfLibraryOrganization.Folder folder) {
        String name=(String)JOptionPane.showInputDialog(this,"새 이름을 입력해 주세요.",
            "폴더 이름 변경",JOptionPane.PLAIN_MESSAGE,null,null,folder.name());
        if(name==null || name.strip().equals(folder.name()))return;
        try {organization.renameFolder(folder.id(),name);completeSelectionAction();refresh();}
        catch(IOException error) {showFolderError(error);}
    }

    private void showIconPicker(PdfLibraryOrganization.Folder folder,JComponent anchor) {
        JPopupMenu picker=new JPopupMenu();
        JPanel choices=new JPanel(new GridLayout(0,6,5,5));
        choices.setBorder(new EmptyBorder(8,8,8,8));
        for(String[] choice:FOLDER_ICONS) {
            boolean noIcon=choice[0].equals("folder");
            JButton button=new JButton(new FolderGlyph(noIcon?"none":choice[0],noIcon?LibraryDesign.MUTED:folderColor(folder),33));
            button.setToolTipText(choice[1]);
            button.setPreferredSize(new Dimension(52,50));
            button.addActionListener(event -> {
                picker.setVisible(false);
                try {organization.setIcon(folder.id(),choice[0]);completeSelectionAction();refresh();}
                catch(IOException error) {showFolderError(error);}
            });
            choices.add(button);
        }
        picker.add(choices);picker.show(anchor,0,anchor.getHeight());
    }

    private void showColorPicker(PdfLibraryOrganization.Folder folder,JComponent anchor) {
        JPopupMenu picker=new JPopupMenu();
        JPanel choices=new JPanel(new GridLayout(4,5,5,5));
        choices.setBorder(new EmptyBorder(8,8,8,8));
        for(String[] choice:FOLDER_COLORS) {
            Color swatch=Color.decode(choice[1]);
            JButton button=new JButton() {
                @Override protected void paintComponent(Graphics graphics) {
                    Graphics2D g=(Graphics2D)graphics.create();
                    try {
                        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                        g.setColor(swatch);g.fillRoundRect(3,3,getWidth()-6,getHeight()-6,9,9);
                    } finally {g.dispose();}
                }
            };
            button.setContentAreaFilled(false);button.setBorderPainted(false);
            button.setToolTipText(choice[0]);
            button.setPreferredSize(new Dimension(35,35));
            button.addActionListener(event -> {
                picker.setVisible(false);
                try {organization.setColor(folder.id(),choice[1]);completeSelectionAction();refresh();}
                catch(IOException error) {showFolderError(error);}
            });
            choices.add(button);
        }
        picker.add(choices);picker.show(anchor,0,anchor.getHeight());
    }

    private void showFolderError(IOException error) {
        JOptionPane.showMessageDialog(this,error.getMessage(),"폴더",JOptionPane.ERROR_MESSAGE);
    }

    private void createFolder() {
        String name=JOptionPane.showInputDialog(this,"폴더 이름을 입력해 주세요.","새 폴더 만들기",
            JOptionPane.PLAIN_MESSAGE);
        if(name==null)return;
        try {
            if(organization==null)organization=PdfLibraryOrganization.load(root);
            organization.createFolder(currentFolderId,name);
            refresh();
        } catch(IOException error) {
            JOptionPane.showMessageDialog(this,error.getMessage(),"새 폴더 만들기",JOptionPane.ERROR_MESSAGE);
        }
    }

    @Override public void doLayout() {
        super.doLayout();
        setColumns();
    }

    private JPanel documentCard(PdfLibraryStore.Item item) {
        JPanel card=baseCard();documentCards.put(item.id(),card);
        if(selectionMode&&selectedIds.contains(item.id()))((StudyTheme.RoundedPanel)card).setOutline(BLUE);
        JLabel cover=new LibraryShelfDesign.PaperCover();ImageIcon icon=thumbnails.get(item.id());
        if(icon!=null){cover.setText("");cover.setIcon(icon);}covers.put(item.id(),cover);
        JCheckBox selected=new JCheckBox();selected.setOpaque(false);selected.setVisible(selectionMode);selected.setSelected(selectedIds.contains(item.id()));selected.setToolTipText(item.name()+" 선택");
        selected.addActionListener(event->{if(selected.isSelected())selectedIds.add(item.id());else selectedIds.remove(item.id());showItems();});
        JPanel preview=new JPanel(null){@Override public void doLayout(){int width=Math.min(198,getWidth());cover.setBounds((getWidth()-width)/2,0,width,186);selected.setBounds(Math.max(0,(getWidth()-198)/2),5,24,24);}};
        preview.setOpaque(false);preview.add(cover);preview.add(selected);preview.setComponentZOrder(selected,0);
        JLabel pages=new JLabel(gridPageCount(item.id()));pages.putClientProperty("library.gridMetadata",true);pageCountLabels.put(item.id(),pages);
        JButton menu=new JButton();menu.setToolTipText(item.name()+" 메뉴");LibraryShelfDesign.menu(menu);JPopupMenu actions=documentActions(item,menu);
        card.add(LibraryShelfDesign.content(preview,item.name(),menu,pages,modifiedText(item)),BorderLayout.CENTER);
        clickable(card,()->animateOpen(card,()->openOrSelect(item)));installContextMenu(card,actions,true);
        enableDocumentDrag(card,item.id(),()->LibraryDragPreview.capture(cover));
        installDrop(card);return card;
    }

    private JPanel importPlaceholder(PdfBatchQueue.Snapshot item) {
        if(listView){
            JPanel row=new JPanel(new BorderLayout(12,0));row.setOpaque(false);
            row.setBorder(new EmptyBorder(12,16,12,16));
            row.add(new JLabel("PDF  ·  "+item.name()),BorderLayout.CENTER);
            row.add(new JLabel("가져오는 중…"),BorderLayout.EAST);return row;
        }
        JPanel card=baseCard();JPanel preview=new JPanel(new BorderLayout());preview.setOpaque(false);
        preview.add(new LibraryShelfDesign.PaperCover(),BorderLayout.CENTER);
        JButton menu=new JButton();menu.setVisible(false);
        card.add(LibraryShelfDesign.content(preview,item.name(),menu,new JLabel("PDF · 가져오는 중…"),""),BorderLayout.CENTER);
        return card;
    }

    private JPopupMenu folderActions(PdfLibraryOrganization.Folder folder,JPanel card,JButton menu) {
        JPopupMenu actions=new JPopupMenu();
        if(PdfLibraryOrganization.isTrash(folder.id())){
            JMenuItem openTrash=new JMenuItem("휴지통 열기");openTrash.addActionListener(event->enterFolder(folder.id()));actions.add(openTrash);
            LibraryShelfDesign.popup(actions);menu.addActionListener(event->showContextMenu(actions,menu,0,menu.getHeight()));return actions;
        }
        boolean permanent=organization.isFolderInTrash(folder.id());
        JMenuItem rename=new JMenuItem("이름 변경"),changeIcon=new JMenuItem("아이콘 변경"),changeColor=new JMenuItem("색상 변경"),
            openFolder=new JMenuItem("폴더 열기"),remove=new JMenuItem(permanent?"영구 삭제하기":"휴지통으로 이동시키기");
        rename.addActionListener(event->renameFolder(folder));changeIcon.addActionListener(event->showIconPicker(folder,menu));
        changeColor.addActionListener(event->showColorPicker(folder,menu));
        openFolder.addActionListener(event->enterFolder(folder.id()));remove.addActionListener(event->{
            if(permanent)permanentlyDeleteSelection(List.of(),List.of(folder.id()));else moveSelectionToTrash(List.of(),List.of(folder.id()));});
        actions.add(rename);actions.add(changeIcon);actions.add(changeColor);actions.addSeparator();actions.add(openFolder);actions.addSeparator();if(permanent){JMenuItem restore=new JMenuItem("복원하기");restore.addActionListener(event->restoreSelection(List.of(),List.of(folder.id())));actions.add(restore);}actions.add(remove);
        LibraryShelfDesign.popup(actions);menu.addActionListener(event->showContextMenu(actions,menu,0,menu.getHeight()));return actions;
    }
    private JPopupMenu documentActions(PdfLibraryStore.Item item,JButton menu) {
        JPopupMenu actions=new JPopupMenu();
        boolean permanent=organization!=null&&organization.isDocumentInTrash(item.id());
        JMenuItem rename=new JMenuItem("이름 바꾸기"),removeFile=new JMenuItem(permanent?"영구 삭제하기":"휴지통으로 이동시키기"),removeData=new JMenuItem("데이터 삭제"),
            reveal=new JMenuItem("파일 탐색기에서 보기"),info=new JMenuItem("정보보기");
        rename.addActionListener(event->renameItem(item));removeFile.addActionListener(event->{
            if(permanent)permanentlyDeleteSelection(List.of(item.id()),List.of());else moveSelectionToTrash(List.of(item.id()),List.of());});
        removeData.addActionListener(event->deleteItem(item,false));reveal.addActionListener(event->revealStoredPdf(item));info.addActionListener(event->showInfo(item));
        actions.add(rename);actions.addSeparator();if(permanent){JMenuItem restore=new JMenuItem("복원하기");restore.addActionListener(event->restoreSelection(List.of(item.id()),List.of()));actions.add(restore);}actions.add(removeFile);actions.add(removeData);actions.addSeparator();actions.add(reveal);actions.add(info);
        LibraryShelfDesign.popup(actions);menu.addActionListener(event->showContextMenu(actions,menu,0,menu.getHeight()));return actions;
    }

    private static final int[] LIST_COLUMN_WIDTHS={28,220,64,110,110,72,32};
    private static JLabel listLabel(String text,boolean name) {
        JLabel label=new JLabel(text);label.setFont(LibraryDesign.font(name?Font.BOLD:Font.PLAIN,name?14:12));
        label.setForeground(name?TEXT:MUTED);label.setToolTipText(text);return label;
    }
    private static void listColumns(JPanel row,Component...cells) {
        row.setLayout(new GridBagLayout());row.setAlignmentX(Component.LEFT_ALIGNMENT);
        row.setBorder(new EmptyBorder(0,12,0,12));
        for(int i=0;i<cells.length;i++){
            Component cell=cells[i];cell.setPreferredSize(new Dimension(LIST_COLUMN_WIDTHS[i],28));
            cell.setMinimumSize(new Dimension(i==1?60:LIST_COLUMN_WIDTHS[i],28));
            GridBagConstraints c=new GridBagConstraints();c.gridx=i;c.gridy=0;c.weightx=i==1?1:0;
            c.fill=GridBagConstraints.HORIZONTAL;c.insets=new Insets(0,6,0,6);row.add(cell,c);
        }
    }
    private JPanel listHeader() {
        JPanel header=new JPanel();header.setBackground(LibraryDesign.PREVIEW);header.setName("library-list-header");
        String[] names={"","이름","종류","업로드 일자","최근 열람","페이지 수",""};
        Component[] labels=Arrays.stream(names).map(s->listLabel(s,false)).toArray(Component[]::new);listColumns(header,labels);
        header.setPreferredSize(new Dimension(LIST_MIN_WIDTH,38));header.setMaximumSize(new Dimension(Integer.MAX_VALUE,38));return header;
    }
    private JPanel listRow(String id,boolean folder,String name,Icon icon,Component nameCell,JLabel added,JLabel opened,JLabel pages,JButton menu) {
        JPanel row=new AnimatedCard(true);row.setName("library-list-"+(folder?"folder-":"document-")+id);
        JLabel glyph=new JLabel(icon,SwingConstants.CENTER);
        listColumns(row,glyph,nameCell,listLabel(folder?"폴더":"파일",false),added,opened,pages,menu);
        row.setPreferredSize(new Dimension(LIST_MIN_WIDTH,54));row.setMaximumSize(new Dimension(Integer.MAX_VALUE,54));
        row.getAccessibleContext().setAccessibleName(name+(folder?" 폴더":" PDF 파일"));
        if(folder){folderCards.put(id,row);folderIcons.put(id,glyph);}else documentCards.put(id,row);
        return row;
    }
    private static JButton listMenu(String name) {
        JButton menu=new JButton(LibraryDesign.icon("dots",18,18));menu.setToolTipText(name+" 메뉴");
        menu.getAccessibleContext().setAccessibleName(name+" 메뉴");menu.setBorder(new EmptyBorder(0,0,0,0));
        menu.setContentAreaFilled(false);menu.setBorderPainted(false);menu.setFocusPainted(false);return menu;
    }
    private JPanel folderRow(PdfLibraryOrganization.Folder folder) {
        Icon original=PdfLibraryOrganization.isTrash(folder.id())?libraryFolderIcon(folder)
            :LibraryDesign.coloredIcon("folder",36,32,folderColor(folder));Icon icon=new Icon(){
            public int getIconWidth(){return 24;}public int getIconHeight(){return 24;}
            public void paintIcon(Component c,Graphics graphics,int x,int y){Graphics2D g=(Graphics2D)graphics.create();
                try{double scale=24d/Math.max(original.getIconWidth(),original.getIconHeight());g.translate(x+(24-original.getIconWidth()*scale)/2,y+(24-original.getIconHeight()*scale)/2);g.scale(scale,scale);original.paintIcon(c,g,0,0);}finally{g.dispose();}}
        };
        JButton menu=listMenu(folder.name());JLabel added=listLabel("—",false),opened=listLabel("—",false);
        added.setToolTipText("폴더에는 업로드 일자가 없어요.");opened.setToolTipText("폴더 열람 일자는 기록되어 있지 않아요.");
        Component nameCell=listLabel(folder.name(),true);
        if(selectionMode&&!PdfLibraryOrganization.isTrash(folder.id())){
            JPanel choice=new JPanel(new BorderLayout(6,0));choice.setOpaque(false);JCheckBox selected=new JCheckBox();selected.setOpaque(false);
            selected.setSelected(selectedFolderIds.contains(folder.id()));selected.setToolTipText(folder.name()+" 선택");selected.addActionListener(event->openOrSelectFolder(folder));
            choice.add(selected,BorderLayout.WEST);choice.add(nameCell,BorderLayout.CENTER);nameCell=choice;
        }
        JPanel row=listRow(folder.id(),true,folder.name(),icon,nameCell,added,opened,listLabel("—",false),menu);
        if(selectionMode&&selectedFolderIds.contains(folder.id()))((StudyTheme.RoundedPanel)row).setOutline(BLUE);
        JPopupMenu actions=folderActions(folder,row,menu);clickable(row,()->openOrSelectFolder(folder));
        installContextMenu(row,actions,true);if(!PdfLibraryOrganization.isTrash(folder.id()))enableLibraryDrag(row,new LibraryDrag(folder.id(),true),()->LibraryDragPreview.icon(original,row));installDrop(row,folder.id(),true);return row;
    }
    private String pageCountText(String id){Integer pages=pageCounts.get(id);return pages==null?"…":pages>0?pages+"쪽":"—";}
    private JPanel documentRow(PdfLibraryStore.Item item) {
        JLabel name=listLabel(item.name(),true),pages=listLabel(pageCountText(item.id()),false);pageCountLabels.put(item.id(),pages);
        Component nameCell=name;
        if(selectionMode){
            JPanel choice=new JPanel(new BorderLayout(6,0));choice.setOpaque(false);JCheckBox selected=new JCheckBox();selected.setOpaque(false);
            selected.setSelected(selectedIds.contains(item.id()));selected.setToolTipText(item.name()+" 선택");
            selected.addActionListener(event->{if(selected.isSelected())selectedIds.add(item.id());else selectedIds.remove(item.id());showItems();});
            choice.add(selected,BorderLayout.WEST);choice.add(name,BorderLayout.CENTER);nameCell=choice;
        }
        JButton menu=listMenu(item.name());
        JPanel row=listRow(item.id(),false,item.name(),dev.synesis.poc.ui.MistWorkspaceTheme.icon("file",20),nameCell,
            listLabel(DATE.format(item.addedAt().atZone(ZoneId.of("Asia/Seoul"))),false),
            listLabel(DATE.format(item.lastOpenedAt().atZone(ZoneId.of("Asia/Seoul"))),false),pages,menu);
        if(selectionMode&&selectedIds.contains(item.id()))((StudyTheme.RoundedPanel)row).setOutline(BLUE);
        JPopupMenu actions=documentActions(item,menu);clickable(row,()->animateOpen(row,()->openOrSelect(item)));installContextMenu(row,actions,true);
        enableDocumentDrag(row,item.id(),()->LibraryDragPreview.icon(
            dev.synesis.poc.ui.MistWorkspaceTheme.icon("file",20),row));
        installDrop(row);return row;
    }

    private void enableDocumentDrag(JComponent card,String id,java.util.function.Supplier<BufferedImage> previewSupplier) {
        if(!selectionMode) {enableLibraryDrag(card,new LibraryDrag(id,false),previewSupplier);return;}
        String originFolder=currentFolderId;
        TransferHandler handler=new TransferHandler() {
            @Override public int getSourceActions(JComponent source) {return MOVE;}
            @Override protected Transferable createTransferable(JComponent source) {
                finishSelectionDrag();
                List<String> ids=dragDocumentIds(id);
                BufferedImage preview;
                if(ids.size()>1) {
                    List<LibrarySelectionDrag.Sprite> sprites=new ArrayList<>();
                    Rectangle viewport=SwingUtilities.convertRectangle(scroll.getViewport(),
                        new Rectangle(scroll.getViewport().getSize()),dropLayer);
                    for(String selected:ids) {
                        JComponent artwork=documentArtwork(selected);
                        if(artwork==null || artwork.getWidth()<=0 || artwork.getHeight()<=0)continue;
                        Point origin=SwingUtilities.convertPoint(artwork,artwork.getWidth()/2,artwork.getHeight()/2,dropLayer);
                        if(!viewport.contains(origin))continue;
                        sprites.add(new LibrarySelectionDrag.Sprite(LibraryDragPreview.capture(artwork),origin));
                        if(sprites.size()>=LibrarySelectionDrag.MAX_SPRITES)break;
                    }
                    if(sprites.isEmpty())sprites.add(new LibrarySelectionDrag.Sprite(previewSupplier.get(),
                        SwingUtilities.convertPoint(source,source.getWidth()/2,source.getHeight()/2,dropLayer)));
                    preview=LibraryDragPreview.stack(sprites.stream().map(LibrarySelectionDrag.Sprite::image).toList(),ids.size());
                    // The native transfer still owns drop/hover. Only its visual is painted in our existing layer.
                    setDragImage(new BufferedImage(1,1,BufferedImage.TYPE_INT_ARGB_PRE));
                    setDragImageOffset(new Point());
                    Point pointer=dragPointer(source);
                    dropOverlay.selection=new LibrarySelectionDrag(dropLayer,sprites,preview,pointer);
                    if(!GraphicsEnvironment.isHeadless()) {
                        LibrarySelectionDrag motion=dropOverlay.selection;
                        selectionDragListener=event->{
                            Point location=event.getLocation();
                            Runnable update=()->{
                                if(dropOverlay.selection!=motion || !dropLayer.isShowing())return;
                                SwingUtilities.convertPointFromScreen(location,dropLayer);motion.move(location);
                            };
                            if(SwingUtilities.isEventDispatchThread())update.run();else SwingUtilities.invokeLater(update);
                        };
                        DragSource.getDefaultDragSource().addDragSourceMotionListener(selectionDragListener);
                    }
                } else {
                    preview=previewSupplier.get();setDragImage(preview);
                    setDragImageOffset(new Point(-preview.getWidth()/2,-preview.getHeight()/2));
                }
                LibraryDrag payload=new LibraryDrag(id,false,preview,ids);activeDocumentDrag=payload;
                cancelSelectionDrag=()->exportDone(source,null,NONE);
                return documentTransfer(payload);
            }
            @Override protected void exportDone(JComponent source,Transferable data,int action) {
                clearMoveHint();
                setDragImage(null);
                if(dropOverlay.selection!=null && dropOverlay.selection.isReturning())return;
                if(action==NONE && dropOverlay.selection!=null) {
                    if(selectionDragListener!=null) {
                        DragSource.getDefaultDragSource().removeDragSourceMotionListener(selectionDragListener);selectionDragListener=null;
                    }
                    cancelFolderHover();
                    if(!currentFolderId.equals(originFolder)){currentFolderId=originFolder;showItems();}
                    LibrarySelectionDrag motion=dropOverlay.selection;
                    motion.returnToOrigins(()->{if(dropOverlay.selection==motion){finishSelectionDrag();showItems();}});
                    return;
                }
                finishSelectionDrag();
                // Hover navigation may have left the original selection outside the current folder.
                showItems();
            }
        };
        installLibraryDrag(card,handler);
    }

    private List<String> dragDocumentIds(String sourceId) {
        if(!selectedIds.contains(sourceId))return List.of(sourceId);
        List<String> ids=new ArrayList<>();ids.add(sourceId);
        for(PdfLibraryStore.Item item:items)
            if(!item.id().equals(sourceId) && selectedIds.contains(item.id()))ids.add(item.id());
        return List.copyOf(ids);
    }

    private JComponent documentArtwork(String id) {
        if(!listView)return covers.get(id);
        JPanel row=documentCards.get(id);
        return row!=null && row.getComponentCount()>0 && row.getComponent(0) instanceof JComponent icon?icon:null;
    }

    private Point dragPointer(JComponent source) {
        if(!GraphicsEnvironment.isHeadless() && dropLayer.isShowing()) {
            PointerInfo info=MouseInfo.getPointerInfo();
            if(info!=null) {Point location=info.getLocation();SwingUtilities.convertPointFromScreen(location,dropLayer);return location;}
        }
        return SwingUtilities.convertPoint(source,source.getWidth()/2,source.getHeight()/2,dropLayer);
    }

    private void finishSelectionDrag() {
        clearMoveHint();
        if(selectionDragListener!=null) {
            DragSource.getDefaultDragSource().removeDragSourceMotionListener(selectionDragListener);selectionDragListener=null;
        }
        if(dropOverlay.selection!=null) {dropOverlay.selection.close();dropOverlay.selection=null;}
        activeDocumentDrag=null;cancelSelectionDrag=null;cancelFolderHover();
    }

    private static Transferable documentTransfer(LibraryDrag payload) {
        return new Transferable() {
            @Override public DataFlavor[] getTransferDataFlavors() {return new DataFlavor[]{DOCUMENT_FLAVOR};}
            @Override public boolean isDataFlavorSupported(DataFlavor flavor) {return DOCUMENT_FLAVOR.equals(flavor);}
            @Override public Object getTransferData(DataFlavor flavor) throws UnsupportedFlavorException {
                if(!isDataFlavorSupported(flavor))throw new UnsupportedFlavorException(flavor);
                return payload;
            }
        };
    }

    private void enableLibraryDrag(Component component,LibraryDrag dragged,
                                          java.util.function.Supplier<BufferedImage> previewSupplier) {
        // One handler per card, one current artwork capture per drag, no per-move image work.
        TransferHandler handler=new TransferHandler() {
            @Override public int getSourceActions(JComponent source) {return MOVE;}
            @Override protected Transferable createTransferable(JComponent source) {
                clearMoveHint();
                BufferedImage preview=previewSupplier.get();
                setDragImage(preview);
                setDragImageOffset(new Point(-preview.getWidth()/2,-preview.getHeight()/2));
                LibraryDrag payload=new LibraryDrag(dragged.id(),dragged.folder(),preview);
                return documentTransfer(payload);
            }
            @Override protected void exportDone(JComponent source,Transferable data,int action) {
                // The drop's existing arrival animation retains its own reference if needed.
                clearMoveHint();cancelFolderHover();
                setDragImage(null);
            }
        };
        installLibraryDrag(component,handler);
    }

    private static void installLibraryDrag(Component component,TransferHandler handler) {
        if(component instanceof JComponent target && !(component instanceof AbstractButton)) {
            target.setTransferHandler(handler);
            LibraryCardGesture gesture=(LibraryCardGesture)target.getClientProperty(LibraryCardGesture.class);
            if(gesture==null){gesture=new LibraryCardGesture(target,null);installCardGesture(target,gesture);}
            gesture.draggable=true;
        }
        if(component instanceof Container container)
            for(Component child:container.getComponents())installLibraryDrag(child,handler);
    }

    private void openOrSelect(PdfLibraryStore.Item item) {
        if(selectionMode) {
            if(!selectedIds.add(item.id()))selectedIds.remove(item.id());
            showItems();
        } else open.accept(item.source());
    }

    private void showInfo(PdfLibraryStore.Item item) {
        String uploaded=DATE_TIME.format(item.addedAt().atZone(ZoneId.systemDefault()));
        String opened=DATE_TIME.format(item.lastOpenedAt().atZone(ZoneId.systemDefault()));
        JOptionPane.showMessageDialog(this,
            "파일: "+item.name()+"\n파일 확장자: .pdf\n업로드 일자: "+uploaded+"\n최종 열람 일자: "+opened,
            "파일 정보",JOptionPane.INFORMATION_MESSAGE);
    }

    private void renameItem(PdfLibraryStore.Item item) {
        String name = (String) JOptionPane.showInputDialog(this,
            "새 이름을 입력해 주세요.", "이름 바꾸기", JOptionPane.PLAIN_MESSAGE,
            null, null, item.name());
        if (name == null || name.strip().equals(item.name())) return;
        if (name.isBlank()) {
            JOptionPane.showMessageDialog(this, "이름을 입력해 주세요.",
                "이름 바꾸기", JOptionPane.WARNING_MESSAGE);
            return;
        }
        try {
            PdfLibraryStore.rename(root, item.id(), name);
            completeSelectionAction();refresh();
        } catch (IOException error) {
            JOptionPane.showMessageDialog(this, "이름을 저장하지 못했어요.\n" + error.getMessage(),
                "이름 바꾸기", JOptionPane.ERROR_MESSAGE);
        }
    }

    private void revealStoredPdf(PdfLibraryStore.Item item) {
        Path source = item.source().toAbsolutePath().normalize();
        loader.execute(() -> {
            try {
                if (!Files.isRegularFile(source)) {
                    throw new IOException("저장된 PDF 복제본을 찾을 수 없어요: " + source);
                }
                String os = System.getProperty("os.name", "").toLowerCase(Locale.ROOT);
                if (os.contains("mac")) {
                    new ProcessBuilder("open", "-R", source.toString()).start();
                } else if (os.contains("win")) {
                    new ProcessBuilder("explorer.exe", "/select," + source).start();
                } else if (Desktop.isDesktopSupported()
                        && Desktop.getDesktop().isSupported(Desktop.Action.BROWSE_FILE_DIR)) {
                    Desktop.getDesktop().browseFileDirectory(source.toFile());
                } else {
                    new ProcessBuilder("xdg-open", source.getParent().toString()).start();
                }
            } catch (Exception failure) {
                SwingUtilities.invokeLater(() -> JOptionPane.showMessageDialog(this,
                    "PDF 복제본 위치를 열지 못했어요.\n" + failure.getMessage(),
                    "파일 탐색기에서 보기", JOptionPane.ERROR_MESSAGE));
            }
        });
    }

    private void deleteItem(PdfLibraryStore.Item item, boolean file) {
        deleteItems(List.of(item),file);
    }

    private void deleteSelected(boolean file) {
        List<String> documents=List.copyOf(selectedIds),folders=List.copyOf(selectedFolderIds);
        if(file){
            if(isTrashView())permanentlyDeleteSelection(documents,folders);else moveSelectionToTrash(documents,folders);
            return;
        }
        try{
            Set<String> ids=new HashSet<>(documents);
            for(String id:folders)ids.addAll(organization.documentsInTree(id));
            List<PdfLibraryStore.Item> chosen=items.stream().filter(item->ids.contains(item.id())).toList();
            if(!chosen.isEmpty())deleteItems(chosen,false);
        }catch(IOException error){showFolderError(error);}
    }

    private void moveSelectionToTrash(List<String> documents,List<String> folders){
        if(documents.isEmpty()&&folders.isEmpty())return;
        List<String> ids=List.copyOf(documents),folderIds=List.copyOf(folders);
        revision++;
        loader.execute(()->{
            try{
                PdfLibraryOrganization.load(root).moveToTrash(ids,folderIds);
                SwingUtilities.invokeLater(()->{completeSelectionAction();refresh();});
            }catch(IOException error){SwingUtilities.invokeLater(()->{showFolderError(error);refresh();});}
        });
    }

    private void restoreSelection(List<String> documents,List<String> folders){
        if(documents.isEmpty()&&folders.isEmpty())return;
        List<String> ids=List.copyOf(documents),folderIds=List.copyOf(folders);String expectedRevision=organization.revision();
        revision++;
        loader.execute(()->{
            try{
                var result=PdfLibraryOrganization.load(root).restoreFromTrash(expectedRevision,ids,folderIds);
                SwingUtilities.invokeLater(()->{
                    completeSelectionAction();refresh();
                    if(result.homeFallbackCount()>0)JOptionPane.showMessageDialog(this,"원래 위치를 확인할 수 없거나 사용할 수 없는 항목 "+result.homeFallbackCount()+"개는 홈화면으로 복원했어요.","복원 완료",JOptionPane.INFORMATION_MESSAGE);
                });
            }catch(IOException error){SwingUtilities.invokeLater(()->{showFolderError(error);refresh();});}
        });
    }

    private void permanentlyDeleteSelection(List<String> documents,List<String> folders){
        if(documents.isEmpty()&&folders.isEmpty())return;
        PdfLibraryOrganization snapshot;
        Set<String> ids=new HashSet<>(documents);
        List<String> folderIds=List.copyOf(folders);
        try{
            snapshot=PdfLibraryOrganization.load(root);
            for(String id:folderIds){
                if(PdfLibraryOrganization.isTrash(id)||!snapshot.isFolderInTrash(id))throw new IOException("휴지통 안의 항목만 영구 삭제할 수 있어요.");
                ids.addAll(snapshot.documentsInTree(id));
            }
            for(String id:ids)if(!snapshot.isDocumentInTrash(id))throw new IOException("휴지통 안의 항목만 영구 삭제할 수 있어요.");
        }catch(IOException error){showFolderError(error);return;}
        String message="선택한 폴더 "+folderIds.size()+"개와 PDF "+ids.size()+"개를 영구 삭제하시겠어요?\n\n"
            +"PDF 복제본과 학습 데이터가 영구 삭제되며 되돌릴 수 없어요.\n"
            +"누적 사용량 기록과 처음 업로드한 원본 PDF는 남아요.";
        int answer=JOptionPane.showOptionDialog(this,message,"영구 삭제 확인",JOptionPane.DEFAULT_OPTION,
            JOptionPane.WARNING_MESSAGE,null,new Object[]{"영구 삭제하기","취소"},"취소");
        if(answer!=0)return;
        CompletableFuture<Void> released;
        try{released=CompletableFuture.allOf(ids.stream().map(releaseDocument).toArray(CompletableFuture[]::new));}
        catch(Exception error){showDeleteError(error);return;}
        String expectedRevision=snapshot.revision();List<String> chosen=List.copyOf(ids);revision++;
        loader.execute(()->{
            try{
                released.join();PdfLibraryOrganization.load(root).permanentlyDeleteTrashed(expectedRevision,chosen,folderIds);
                SwingUtilities.invokeLater(()->{completeSelectionAction();refresh();});
            }catch(Exception error){SwingUtilities.invokeLater(()->showDeleteError(error));}
        });
    }

    private void deleteItems(List<PdfLibraryStore.Item> chosen,boolean file) {
        if(file){
            List<String> ids=chosen.stream().map(PdfLibraryStore.Item::id).toList();
            if(isTrashView())permanentlyDeleteSelection(ids,List.of());else moveSelectionToTrash(ids,List.of());
            return;
        }
        String target=chosen.size()==1?"‘"+chosen.get(0).name()+"’":chosen.size()+"개 문서";
        String message=target+"의 데이터를 정말 삭제하시겠어요?\n\n"
                +"생성된 요약·개념 및 페이지 AI 분석 결과가 삭제됩니다.\n"
                +"PDF와 추출 원문은 남지만, 다시 열어 요약·개념을 만들려면\n"
                +"PDF 페이지를 다시 분석해야 해서 시간이 걸리고 API 비용이 발생할 수 있습니다.";
        int answer=JOptionPane.showOptionDialog(this,message,"데이터 삭제 확인",
            JOptionPane.DEFAULT_OPTION,JOptionPane.WARNING_MESSAGE,null,
            new Object[]{"삭제","취소"},"취소");
        if(answer!=0)return;
        CompletableFuture<Void> released;
        try {released=CompletableFuture.allOf(chosen.stream()
            .map(item->releaseDocument.apply(item.id())).toArray(CompletableFuture[]::new));}
        catch(Exception failure) {showDeleteError(failure);return;}
        revision++;
        loader.execute(() -> {
            try {
                released.join();
                for(PdfLibraryStore.Item item:chosen) {
                    PdfLibraryStore.deleteGeneratedData(root,item.id());
                }
                SwingUtilities.invokeLater(() -> {
                    completeSelectionAction();
                    refresh();
                });
            } catch(Exception failure) {SwingUtilities.invokeLater(() -> showDeleteError(failure));}
        });
    }

    private void showDeleteError(Exception failure) {
        Throwable cause=failure.getCause()==null?failure:failure.getCause();
        JOptionPane.showMessageDialog(this,"삭제하지 못했습니다: "+cause.getMessage(),"PDF 삭제",JOptionPane.ERROR_MESSAGE);
        refresh();
    }

    private JPanel baseCard() {
        JPanel card = new AnimatedCard();
        card.setBorder(new EmptyBorder(0,0,0,0));
        card.setPreferredSize(new Dimension(252,LibraryShelfDesign.HEIGHT));
        card.setMinimumSize(new Dimension(198,LibraryShelfDesign.HEIGHT));
        return card;
    }

    private void animateOpen(JPanel card,Runnable action) {
        if(selectionMode) {action.run();return;}
        ((AnimatedCard)card).play(action);
    }

    /** PDF covers are data, fitted in the 160 × 86 paper slot without cropping. */
    private static final class FittedCover extends JLabel {
        FittedCover(){super("PDF",SwingConstants.CENTER);}
        @Override protected void paintComponent(Graphics graphics) {
            if(!(getIcon() instanceof ImageIcon icon)){super.paintComponent(graphics);return;}
            Graphics2D g=(Graphics2D)graphics.create();
            try {
                g.setColor(Color.WHITE);g.fillRect(0,0,getWidth(),getHeight());
                double scale=Math.min(getWidth()/(double)Math.max(1,icon.getIconWidth()),getHeight()/(double)Math.max(1,icon.getIconHeight()));
                int width=Math.max(1,(int)Math.round(icon.getIconWidth()*scale));
                int height=Math.max(1,(int)Math.round(icon.getIconHeight()*scale));
                g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BICUBIC);
                g.drawImage(icon.getImage(),(getWidth()-width)/2,(getHeight()-height)/2,width,height,null);
            }finally{g.dispose();}
        }
    }

    /** Follow the viewport width; card rows keep their natural 224px height. */
    private final class LibraryShelf extends JPanel implements Scrollable {
        LibraryShelf(){super(new BorderLayout());}
        public Dimension getPreferredScrollableViewportSize(){return new Dimension(1000,700);}
        public int getScrollableUnitIncrement(Rectangle visible,int orientation,int direction){return 24;}
        public int getScrollableBlockIncrement(Rectangle visible,int orientation,int direction){return Math.max(24,visible.height-24);}
        public boolean getScrollableTracksViewportWidth(){return !listView||getParent()==null||getParent().getWidth()>=LIST_MIN_WIDTH+74;}
        public boolean getScrollableTracksViewportHeight(){return false;}
    }

    private static final class AnimatedCard extends dev.synesis.poc.ui.LibraryItemMotion {
        private javax.swing.Timer timer;
        private float progress;

        AnimatedCard() {this(false);}
        AnimatedCard(boolean list) {super(list);}

        void play(Runnable action) {
            if(timer!=null && timer.isRunning())return;
            long started=System.nanoTime();
            timer=new javax.swing.Timer(16,event -> {
                progress=Math.min(1f,(System.nanoTime()-started)/112_000_000f);
                repaint();
                if(progress>=1f) {
                    timer.stop();timer=null;progress=0f;
                    repaint();action.run();
                }
            });
            timer.start();
        }

        @Override public void paint(Graphics graphics) {
            Graphics2D g=(Graphics2D)graphics.create();
            try {
                float eased=progress*progress*progress*(progress*(progress*6-15)+10);
                float pulse=(float)Math.sin(Math.PI*eased);
                double scale=1d-0.02d*pulse;
                g.translate((getWidth()*(1d-scale))/2d,(getHeight()*(1d-scale))/2d);
                g.scale(scale,scale);
                super.paint(g);
                if(pulse>0f) {
                    g.setColor(new Color(118,36,61,Math.round(18*pulse)));
                    g.fillRoundRect(0,0,getWidth()-1,getHeight()-1,15,15);
                }
            } finally {g.dispose();}
        }
    }

    private static void clickable(Component component, Runnable action) {
        if(component instanceof AbstractButton)return;
        component.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        installCardGesture(component,new LibraryCardGesture(component,action));
        if (component instanceof Container container) for (Component child : container.getComponents()) clickable(child, action);
    }

    private static void installCardGesture(Component component,LibraryCardGesture gesture) {
        component.addMouseListener(gesture);component.addMouseMotionListener(gesture);
        if(component instanceof JComponent target)target.putClientProperty(LibraryCardGesture.class,gesture);
    }

    /** One decision per press: jitter stays a click, crossing the threshold stays a drag. */
    private static final class LibraryCardGesture extends java.awt.event.MouseAdapter {
        private final Component component;
        private final Runnable click;
        private Point pressed;
        private boolean draggable,exceeded,exported;
        LibraryCardGesture(Component component,Runnable click){this.component=component;this.click=click;}
        private boolean crossed(Point point){return pressed.distanceSq(point)>=(double)LIBRARY_DRAG_THRESHOLD*LIBRARY_DRAG_THRESHOLD;}
        @Override public void mousePressed(java.awt.event.MouseEvent event) {
            pressed=SwingUtilities.isLeftMouseButton(event)&&!event.isControlDown()&&!event.isPopupTrigger()?event.getPoint():null;
            exceeded=false;exported=false;
        }
        @Override public void mouseDragged(java.awt.event.MouseEvent event) {
            if(pressed==null || (event.getModifiersEx()&java.awt.event.InputEvent.BUTTON1_DOWN_MASK)==0)return;
            exceeded|=crossed(event.getPoint());
            if(exceeded&&draggable&&!exported&&!event.isControlDown()&&component instanceof JComponent target) {
                exported=true;
                target.getTransferHandler().exportAsDrag(target,event,TransferHandler.MOVE);
            }
        }
        @Override public void mouseReleased(java.awt.event.MouseEvent event) {
            boolean activate=pressed!=null&&!exceeded&&!exported&&!crossed(event.getPoint())
                &&SwingUtilities.isLeftMouseButton(event)&&!event.isControlDown()&&!event.isPopupTrigger();
            pressed=null;
            // AWT can omit MOUSE_CLICKED after slight motion; release handles it exactly once.
            if(activate&&click!=null)click.run();
        }
    }

    private static void installContextMenu(Component component,JPopupMenu menu,boolean children) {
        component.addMouseListener(new java.awt.event.MouseAdapter() {
            private void showIfRequested(java.awt.event.MouseEvent event) {
                if(!event.isPopupTrigger())return;
                event.consume();
                if(!menu.isShowing())showContextMenu(menu,event.getComponent(),event.getX(),event.getY());
            }
            @Override public void mousePressed(java.awt.event.MouseEvent event) {showIfRequested(event);}
            @Override public void mouseReleased(java.awt.event.MouseEvent event) {showIfRequested(event);}
        });
        if(children && component instanceof Container container)
            for(Component child:container.getComponents())installContextMenu(child,menu,true);
    }

    private static void showContextMenu(JPopupMenu menu,Component source,int x,int y) {
        if(!source.isShowing())return;
        Object previous=menu.getClientProperty("distanceWatcher");
        if(previous instanceof javax.swing.Timer timer)timer.stop();
        Point origin=new Point(x,y);
        SwingUtilities.convertPointToScreen(origin,source);
        menu.show(source,x,y);
        javax.swing.Timer distanceWatcher=new javax.swing.Timer(80,null);
        menu.putClientProperty("distanceWatcher",distanceWatcher);
        distanceWatcher.addActionListener(event -> {
            if(!menu.isShowing()) {distanceWatcher.stop();return;}
            try {
                PointerInfo pointer=MouseInfo.getPointerInfo();
                if(pointer==null)return;
                Point location=pointer.getLocation();
                Rectangle menuBounds=new Rectangle(menu.getLocationOnScreen(),menu.getSize());
                menuBounds.grow(40,40);
                if(menuBounds.contains(location) || location.distance(origin)<=55)return;
                menu.setVisible(false);
                distanceWatcher.stop();
            } catch(IllegalComponentStateException | SecurityException ignored) {
                distanceWatcher.stop();
            }
        });
        distanceWatcher.start();
    }

    private void choosePdf() {
        JFileChooser chooser = new JFileChooser();
        chooser.setFileFilter(new javax.swing.filechooser.FileNameExtensionFilter("PDF 문서", "pdf"));
        chooser.setMultiSelectionEnabled(true);
        if (chooser.showOpenDialog(this) == JFileChooser.APPROVE_OPTION) {
            List<Path> selected=Arrays.stream(chooser.getSelectedFiles()).map(File::toPath).toList();
            if(selected.isEmpty() && chooser.getSelectedFile()!=null)
                selected=List.of(chooser.getSelectedFile().toPath());
            if(pdfDropHandler!=null)pdfDropHandler.accept(selected);
            else importIntoCurrentFolder(selected);
        }
    }

    private void importIntoCurrentFolder(List<Path> selected) {
        importIntoFolder(selected,currentFolderId);
    }

    private void importIntoFolder(List<Path> selected,String destination) {
        if(selected.isEmpty())return;
        if(destination.isEmpty()) {dispatchImport(selected);return;}
        loader.execute(() -> {
            for(Path path:selected)try {
                MessageDigest digest=MessageDigest.getInstance("SHA-256");
                try(var stream=new DigestInputStream(Files.newInputStream(path),digest)) {
                    stream.transferTo(OutputStream.nullOutputStream());
                }
                String id=HexFormat.of().formatHex(digest.digest());
                if(!Files.isRegularFile(root.resolve(id).resolve("source.pdf")))
                    pendingImports.put(id,destination);
            } catch(Exception ignored) { /* Import reports unreadable PDFs in its normal flow. */ }
            SwingUtilities.invokeLater(() -> dispatchImport(selected));
        });
    }

    private void dispatchImport(List<Path> selected) {
        if(selected.size()==1)open.accept(selected.get(0));
        else importMany.accept(selected);
    }

    private void installDrop(Component component) {installDrop(component,null,false);}

    private boolean canMove(LibraryDrag dragged,String destination) {
        if(organization==null)return false;
        if(!destination.isEmpty() && organization.folder(destination)==null)return false;
        if(!dragged.folder()) {
            if(dragged.documentIds().isEmpty())return false;
            boolean changed=dragged.documentIds().stream().anyMatch(id->!organization.location(id).equals(destination));
            if(!changed)return false;
            // Our active immutable selection was checked at capture; avoid rebuilding sets on every pointer event.
            if(dragged==activeDocumentDrag)return true;
            Set<String> available=new HashSet<>();for(PdfLibraryStore.Item item:items)available.add(item.id());
            return available.containsAll(dragged.documentIds());
        }
        PdfLibraryOrganization.Folder source=organization.folder(dragged.id());
        if(PdfLibraryOrganization.isTrash(dragged.id()))return false;
        if(source==null || source.parentId().equals(destination))return false;
        try {
            if(organization.folderTreeIds(source.id()).contains(destination))return false;
        } catch(IOException ignored) {return false;}
        return PdfLibraryOrganization.isTrash(destination)||organization.folders().stream().noneMatch(sibling -> !sibling.id().equals(source.id())
            && sibling.parentId().equals(destination)
            && sibling.name().equalsIgnoreCase(source.name()));
    }

    private boolean updateMoveHint(LibraryDrag dragged,String destination,Point pointer){
        if(!canMove(dragged,destination)){clearMoveHint();return false;}
        String name=destination.isEmpty()?"홈 화면":organization.folder(destination).name();
        BufferedImage preview=dragged.preview();
        dropOverlay.hint.show(dropLayer,LibraryMoveHint.destinationText(name),pointer,
            preview==null?new Dimension():new Dimension(preview.getWidth(),preview.getHeight()));
        return true;
    }

    private void clearMoveHint(){dropOverlay.hint.clear(dropLayer);}

    private boolean acceptsHomeBreadcrumbNoOp(LibraryDrag dragged,String targetFolder,boolean navigateOnHover) {
        if(!navigateOnHover || targetFolder==null || !targetFolder.isEmpty() || organization==null)return false;
        if(dragged.folder()) {
            PdfLibraryOrganization.Folder folder=organization.folder(dragged.id());
            return folder!=null && !PdfLibraryOrganization.isTrash(folder.id()) && folder.parentId().isEmpty();
        }
        if(dragged.documentIds().isEmpty()
                || dragged.documentIds().stream().anyMatch(id->!organization.location(id).isEmpty()))return false;
        if(dragged==activeDocumentDrag)return true;
        Set<String> available=new HashSet<>();for(PdfLibraryStore.Item item:items)available.add(item.id());
        return available.containsAll(dragged.documentIds());
    }

    private void installDrop(Component component,String targetFolder,boolean navigateOnHover) {
        if (GraphicsEnvironment.isHeadless()) return;
        new DropTarget(component, DnDConstants.ACTION_COPY_OR_MOVE, new DropTargetAdapter() {
            @Override public void dragEnter(DropTargetDragEvent event) { hover(event); }
            @Override public void dragOver(DropTargetDragEvent event) { hover(event); }
            @Override public void dropActionChanged(DropTargetDragEvent event) { hover(event); }
            private void hover(DropTargetDragEvent event) {
                if(event.isDataFlavorSupported(DOCUMENT_FLAVOR)) {
                    event.acceptDrag(DnDConstants.ACTION_MOVE);
                    try {
                        LibraryDrag dragged=(LibraryDrag)event.getTransferable().getTransferData(DOCUMENT_FLAVOR);
                        String destination=targetFolder==null?currentFolderId:targetFolder;
                        Point pointer=SwingUtilities.convertPoint(component,event.getLocation(),dropLayer);
                        if(!updateMoveHint(dragged,destination,pointer)) {
                            if(acceptsHomeBreadcrumbNoOp(dragged,targetFolder,navigateOnHover)
                                    || dragged==activeDocumentDrag && dropOverlay.selection!=null)event.acceptDrag(DnDConstants.ACTION_MOVE);
                            else event.rejectDrag();
                            // A no-op drop can still be a useful route back through the breadcrumb.
                            if(navigateOnHover && targetFolder!=null && canHoverFolder(dragged,targetFolder)) {
                                JComponent icon=folderIcons.get(targetFolder);
                                armFolderHover(targetFolder,icon==null?component:icon);
                            } else cancelFolderHover();
                            return;
                        }
                    } catch(Exception ignored) {event.rejectDrag();clearMoveHint();cancelFolderHover();return;}
                    hideDropOverlay.stop();setDropOverlay(false);
                    if(navigateOnHover && targetFolder!=null) {
                        JComponent icon=folderIcons.get(targetFolder);
                        armFolderHover(targetFolder,icon==null?component:icon);
                    }
                    else cancelFolderHover();
                    return;
                }
                clearMoveHint();
                boolean accepts=event.isDataFlavorSupported(DataFlavor.javaFileListFlavor)
                    && (event.getSourceActions() & DnDConstants.ACTION_COPY)!=0;
                if(accepts) {
                    event.acceptDrag(DnDConstants.ACTION_COPY);
                    hideDropOverlay.stop();setDropOverlay(true);
                } else {
                    event.rejectDrag();hideDropOverlay.stop();setDropOverlay(false);
                }
            }
            @Override public void dragExit(DropTargetEvent event) {
                clearMoveHint();
                hideDropOverlay.restart();cancelFolderHover();
            }
            @Override public void drop(DropTargetDropEvent event) {
                clearMoveHint();
                hideDropOverlay.stop();setDropOverlay(false);cancelFolderHover();
                if(event.isDataFlavorSupported(DOCUMENT_FLAVOR)) {
                    event.acceptDrop(DnDConstants.ACTION_MOVE);
                    LibraryDrag dragged;
                    try {dragged=(LibraryDrag)event.getTransferable().getTransferData(DOCUMENT_FLAVOR);}
                    catch(Exception ignored) {event.dropComplete(false);return;}
                    String destination=targetFolder==null?currentFolderId:targetFolder;
                    if(!canMove(dragged,destination)) {
                        if(dragged==activeDocumentDrag && dropOverlay.selection!=null && cancelSelectionDrag!=null) {
                            // Consume our no-op drop locally: native rejected-drop settling must not delay the return.
                            cancelSelectionDrag.run();event.dropComplete(true);
                        } else event.dropComplete(acceptsHomeBreadcrumbNoOp(dragged,targetFolder,navigateOnHover));
                        return;
                    }
                    boolean moved=false;
                    try {
                        if(dragged.folder())organization.moveFolder(dragged.id(),destination);
                        else organization.moveDocuments(dragged.documentIds(),destination);
                        moved=true;
                        completeSelectionAction();
                        finishSelectionDrag();
                        if(dragged.preview()!=null) {
                            Point from=SwingUtilities.convertPoint(component,event.getLocation(),dropLayer);
                            JComponent target=folderIcons.get(destination);
                            if(target==null)target=breadcrumbTargets.get(destination);
                            if(target!=null) {
                                Point to=SwingUtilities.convertPoint(target,
                                    target.getWidth()/2,target.getHeight()/2,dropLayer);
                                BufferedImage preview=dragged.preview();
                                SwingUtilities.invokeLater(() -> animateFolderDrop(
                                    dragged.id(),dragged.folder(),preview,from,to));
                            } else SwingUtilities.invokeLater(PdfLibraryPanel.this::refresh);
                        } else SwingUtilities.invokeLater(PdfLibraryPanel.this::refresh);
                    } catch(Exception ignored) { /* A rejected move leaves the source in place. */ }
                    event.dropComplete(moved);
                    return;
                }
                if (!event.isDataFlavorSupported(DataFlavor.javaFileListFlavor)
                        || (event.getSourceActions() & DnDConstants.ACTION_COPY)==0) {
                    event.rejectDrop(); return;
                }
                event.acceptDrop(DnDConstants.ACTION_COPY);
                List<Path> files = List.of();
                try {
                    Object data = event.getTransferable().getTransferData(DataFlavor.javaFileListFlavor);
                    if (data instanceof List<?> entries && !entries.isEmpty()
                            && entries.stream().allMatch(entry->entry instanceof File candidate
                                && candidate.isFile() && candidate.getName().toLowerCase(Locale.ROOT).endsWith(".pdf")))
                        files=entries.stream().map(entry->((File)entry).toPath()).toList();
                } catch (Exception ignored) { /* An invalid drop leaves the library untouched. */ }
                event.dropComplete(!files.isEmpty());
                if (!files.isEmpty()) {
                    List<Path> selected=files;
                    SwingUtilities.invokeLater(() -> {
                        if(pdfDropHandler!=null)pdfDropHandler.accept(selected);
                        else importIntoFolder(selected,"");
                    });
                }
            }
        }, true);
        if (component instanceof Container container) for (Component child : container.getComponents())
            installDrop(child,targetFolder,navigateOnHover);
    }

    private void armFolderHover(String id,Component target) {
        if(id.equals(hoverFolderId) && target==hoverFolderTarget)return;
        cancelFolderHover();
        hoverFolderId=id;
        hoverFolderTarget=target instanceof JComponent component?component:null;
        folderHover.restart();
    }

    private boolean canHoverFolder(LibraryDrag dragged,String id) {
        if(organization==null || id.equals(currentFolderId) || (!id.isEmpty() && organization.folder(id)==null))return false;
        if(!dragged.folder())return true;
        try {return !organization.folderTreeIds(dragged.id()).contains(id);}
        catch(IOException ignored) {return false;}
    }

    private void beginFolderBlink() {
        if(hoverFolderId==null || hoverFolderTarget==null)return;
        folderBlinkCount=0;
        hoverFolderTarget.putClientProperty("dragBlinkActive",true);
        hoverFolderTarget.putClientProperty("dragBlink",true);
        hoverFolderTarget.repaint();
        folderBlink.restart();
    }

    private void advanceFolderBlink() {
        if(hoverFolderId==null || hoverFolderTarget==null) {
            cancelFolderHover();return;
        }
        folderBlinkCount++;
        boolean bright=folderBlinkCount<4 && folderBlinkCount%2==0;
        hoverFolderTarget.putClientProperty("dragBlink",bright);
        hoverFolderTarget.repaint();
        if(folderBlinkCount>=4) {
            String destination=hoverFolderId;
            cancelFolderHover();
            enterFolder(destination);
        }
    }

    private void cancelFolderHover() {
        folderHover.stop();folderBlink.stop();hoverFolderId=null;
        if(hoverFolderTarget!=null) {
            hoverFolderTarget.putClientProperty("dragBlink",false);
            hoverFolderTarget.putClientProperty("dragBlinkActive",false);
            hoverFolderTarget.repaint();hoverFolderTarget=null;
        }
    }

    private void animateFolderDrop(String id,boolean folder,BufferedImage image,Point from,Point to) {
        animateFolderDrop(id,folder,image,from,to,()->{});
    }
    private void animateFolderDrop(String id,boolean folder,BufferedImage image,Point from,Point to,Runnable completed) {
        animateFolderDrop(id,folder,image,from,to,completed,()->{});
    }
    private void animateFolderDrop(String id,boolean folder,BufferedImage image,Point from,Point to,Runnable completed,Runnable interrupted) {
        if(flyingTimer!=null){
            flyingTimer.stop();flyingTimer=null;dropOverlay.fly=null;
            Runnable cancelled=flyingInterrupted;flyingInterrupted=null;flyingCompletion=null;
            // Interrupted assistant groups must release their capture, not start the next flight.
            if(cancelled!=null)cancelled.run();
        }
        flyingCompletion=completed;flyingInterrupted=interrupted;
        JPanel source=folder?folderCards.get(id):documentCards.get(id);
        if(source!=null)source.setVisible(false);
        DropOverlay.FlyMotion motion=new DropOverlay.FlyMotion(image,from,to);
        dropOverlay.fly=motion;
        long started=System.nanoTime();
        flyingTimer=new javax.swing.Timer(16,event -> {
            javax.swing.Timer tick=(javax.swing.Timer)event.getSource();
            if(flyingTimer!=tick){tick.stop();return;}
            motion.progress=Math.min(1f,(System.nanoTime()-started)/320_000_000f);
            dropLayer.repaint();
            if(motion.progress>=1f) {
                flyingTimer.stop();flyingTimer=null;
                dropOverlay.fly=null;
                refresh();Runnable finished=flyingCompletion;flyingCompletion=null;flyingInterrupted=null;if(finished!=null)finished.run();
            }
        });
        flyingTimer.start();
        dropLayer.repaint();
    }

    private void setDropOverlay(boolean active) {
        if(dropOverlay.active==active)return;
        dropOverlay.active=active;
        dropLayer.repaint();
    }

    void previewDropOverlay(boolean active) {setDropOverlay(active);}

    private static final class BlinkingFolderIcon implements Icon {
        private final Icon icon;
        BlinkingFolderIcon(Icon icon) {this.icon=icon;}
        @Override public int getIconWidth() {return icon.getIconWidth();}
        @Override public int getIconHeight() {return icon.getIconHeight();}
        @Override public void paintIcon(Component component,Graphics graphics,int x,int y) {
            if(component instanceof JComponent target
                && Boolean.TRUE.equals(target.getClientProperty("dragBlinkActive"))
                && !Boolean.TRUE.equals(target.getClientProperty("dragBlink")))return;
            icon.paintIcon(component,graphics,x,y);
        }
    }

    private static final class FolderGlyph implements Icon {
        private static final Map<String,BufferedImage> CACHE=new LinkedHashMap<>(128,.75f,true) {
            @Override protected boolean removeEldestEntry(Map.Entry<String,BufferedImage> eldest) {
                return size()>256;
            }
        };
        private final String kind;
        private final Color color;
        private final int size;
        private final BufferedImage image;
        FolderGlyph(String kind,Color color,int size) {
            this.kind=kind;this.color=color;this.size=size;
            String key=kind+":"+color.getRGB()+":"+size;
            synchronized(CACHE) {
                this.image=CACHE.computeIfAbsent(key,ignored->createShadowImage());
            }
        }
        @Override public int getIconWidth() {return size;}
        @Override public int getIconHeight() {return size;}
        @Override public void paintIcon(Component component,Graphics graphics,int x,int y) {
            graphics.drawImage(image,x,y,size,size,null);
        }

        private BufferedImage createShadowImage() {
            int scale=Math.max(64,size*2);
            int radius=Math.max(3,Math.round(scale*.045f));
            int padding=radius*2+4,extent=scale+padding*2;
            BufferedImage base=new BufferedImage(extent,extent,BufferedImage.TYPE_INT_ARGB);
            Graphics2D g=base.createGraphics();
            try {
                g.translate(padding,padding);g.scale(scale/64d,scale/64d);
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(color);
                g.setStroke(new BasicStroke(4.5f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                drawGlyph(g);
            } finally {g.dispose();}
            // Bright glyphs need a dark halo on white picker buttons. Bake it once per cache key.
            int luminance=(299*color.getRed()+587*color.getGreen()+114*color.getBlue())/1000;
            int shadowRgb=luminance>=180?0x18202d:0xffffff;
            BufferedImage shadow=new BufferedImage(extent,extent,BufferedImage.TYPE_INT_ARGB);
            for(int y=0;y<extent;y++)for(int x=0;x<extent;x++) {
                int alpha=base.getRGB(x,y)>>>24;
                shadow.setRGB(x,y,((alpha*4/5)<<24)|shadowRgb);
            }
            int taps=radius*2+1;float[] kernel=new float[taps];float sum=0;
            double sigma=Math.max(1,radius/2d);
            for(int i=0;i<taps;i++){double d=i-radius;kernel[i]=(float)Math.exp(-d*d/(2*sigma*sigma));sum+=kernel[i];}
            for(int i=0;i<taps;i++)kernel[i]/=sum;
            BufferedImage horizontal=new java.awt.image.ConvolveOp(new java.awt.image.Kernel(taps,1,kernel),
                java.awt.image.ConvolveOp.EDGE_ZERO_FILL,null).filter(shadow,null);
            BufferedImage blurred=new java.awt.image.ConvolveOp(new java.awt.image.Kernel(1,taps,kernel),
                java.awt.image.ConvolveOp.EDGE_ZERO_FILL,null).filter(horizontal,null);
            BufferedImage result=new BufferedImage(extent,extent,BufferedImage.TYPE_INT_ARGB);
            Graphics2D front=result.createGraphics();
            try {front.drawImage(blurred,0,Math.max(1,scale/48),null);front.drawImage(base,0,0,null);}
            finally {front.dispose();}
            return result;
        }

        private void drawGlyph(Graphics2D g) {
                switch(kind) {
                    case "none" -> {
                        g.drawOval(10,10,44,44);
                        g.drawLine(16,48,48,16);
                    }
                    case "math" -> {
                        g.setFont(new Font(Font.SERIF,Font.BOLD,58));g.drawString("∑",10,53);
                    }
                    case "book" -> {
                        Path2D left=new Path2D.Double();
                        left.moveTo(32,14);left.curveTo(20,8,12,10,6,14);
                        left.lineTo(6,49);left.curveTo(16,45,23,46,32,52);left.closePath();
                        Path2D right=new Path2D.Double();
                        right.moveTo(32,14);right.curveTo(44,8,52,10,58,14);
                        right.lineTo(58,49);right.curveTo(48,45,41,46,32,52);right.closePath();
                        g.draw(left);g.draw(right);g.drawLine(32,14,32,52);
                    }
                    case "atom" -> {
                        for(int angle=0;angle<180;angle+=60) {
                            java.awt.geom.AffineTransform old=g.getTransform();
                            g.rotate(Math.toRadians(angle),32,32);
                            g.drawOval(7,23,50,18);g.setTransform(old);
                        }
                        g.fillOval(27,27,10,10);
                    }
                    case "flask" -> {
                        Path2D flask=new Path2D.Double();
                        flask.moveTo(23,8);flask.lineTo(41,8);flask.moveTo(27,8);
                        flask.lineTo(27,29);flask.lineTo(12,52);flask.quadTo(11,57,17,57);
                        flask.lineTo(47,57);flask.quadTo(53,57,52,52);
                        flask.lineTo(37,29);flask.lineTo(37,8);
                        g.draw(flask);g.drawLine(19,43,45,43);
                    }
                    case "globe" -> {
                        g.drawOval(8,8,48,48);g.drawOval(22,8,20,48);
                        g.drawLine(8,32,56,32);g.drawArc(9,17,46,29,0,180);
                    }
                    case "chart" -> {
                        g.drawLine(9,55,55,55);g.drawLine(9,55,9,10);
                        g.fillRoundRect(16,36,8,19,2,2);
                        g.fillRoundRect(29,25,8,30,2,2);
                        g.fillRoundRect(42,13,8,42,2,2);
                    }
                    case "code" -> {
                        g.drawLine(22,18,9,32);g.drawLine(9,32,22,46);
                        g.drawLine(42,18,55,32);g.drawLine(55,32,42,46);
                        g.drawLine(37,11,27,53);
                    }
                    case "music" -> {
                        g.fillOval(12,42,16,11);g.fillOval(38,36,16,11);
                        g.drawLine(27,47,27,14);g.drawLine(53,41,53,8);
                        g.drawLine(27,14,53,8);
                    }
                    case "medical" -> {
                        g.fillRoundRect(25,8,14,48,3,3);
                        g.fillRoundRect(8,25,48,14,3,3);
                    }
                    case "star" -> {
                        Path2D star=new Path2D.Double();
                        for(int i=0;i<10;i++){double a=-Math.PI/2+i*Math.PI/5,r=i%2==0?25:11;
                            double x=32+Math.cos(a)*r,y=32+Math.sin(a)*r;if(i==0)star.moveTo(x,y);else star.lineTo(x,y);}
                        star.closePath();g.fill(star);
                    }
                    case "heart" -> {
                        Path2D heart=new Path2D.Double();heart.moveTo(32,54);
                        heart.curveTo(0,34,5,8,22,13);heart.quadTo(28,14,32,22);
                        heart.curveTo(45,-2,76,22,32,54);heart.closePath();g.fill(heart);
                    }
                    case "bulb" -> {
                        g.drawOval(16,7,32,33);g.drawLine(23,39,23,47);g.drawLine(41,39,41,47);
                        g.drawLine(23,47,41,47);g.drawLine(26,55,38,55);
                    }
                    case "pencil" -> {
                        Path2D pen=new Path2D.Double();pen.moveTo(12,42);pen.lineTo(42,12);pen.lineTo(53,23);
                        pen.lineTo(23,53);pen.lineTo(9,56);pen.closePath();g.draw(pen);g.drawLine(35,19,46,30);
                    }
                    case "calendar" -> {
                        g.drawRoundRect(9,14,46,42,6,6);g.drawLine(9,26,55,26);
                        g.drawLine(21,8,21,19);g.drawLine(43,8,43,19);
                        for(int y=35;y<51;y+=11)for(int x=20;x<50;x+=12)g.fillOval(x-2,y-2,4,4);
                    }
                    case "camera" -> {
                        g.drawRoundRect(7,20,50,34,7,7);g.drawOval(22,27,20,20);
                        g.drawLine(18,20,23,11);g.drawLine(23,11,41,11);g.drawLine(41,11,46,20);
                    }
                    case "briefcase" -> {
                        g.drawRoundRect(7,20,50,34,5,5);g.drawRoundRect(22,9,20,11,3,3);
                        g.drawLine(8,34,56,34);g.drawLine(28,32,28,39);g.drawLine(36,32,36,39);
                    }
                    case "graduation" -> {
                        Path2D cap=new Path2D.Double();cap.moveTo(5,24);cap.lineTo(32,12);cap.lineTo(59,24);
                        cap.lineTo(32,36);cap.closePath();g.draw(cap);g.drawArc(17,31,30,19,180,180);
                        g.drawLine(17,30,17,40);g.drawLine(47,30,47,40);g.drawLine(58,25,58,47);
                    }
                    case "language" -> {
                        g.setFont(LibraryDesign.font(Font.BOLD,39));g.drawString("A",5,46);
                        g.setFont(LibraryDesign.font(Font.BOLD,25));g.drawString("가",34,49);
                    }
                    case "leaf" -> {
                        Path2D leaf=new Path2D.Double();leaf.moveTo(13,49);leaf.curveTo(0,20,31,10,54,9);
                        leaf.curveTo(57,36,43,60,13,49);leaf.closePath();g.draw(leaf);g.drawLine(10,55,43,22);
                    }
                    case "palette" -> {
                        Path2D art=new Path2D.Double();art.moveTo(48,45);art.curveTo(67,24,45,4,25,10);
                        art.curveTo(0,16,0,47,23,54);art.curveTo(46,63,28,40,48,45);art.closePath();g.draw(art);
                        g.fillOval(17,21,6,6);g.fillOval(30,16,6,6);g.fillOval(43,24,6,6);g.fillOval(13,34,6,6);
                    }
                    case "bolt" -> {
                        Path2D bolt=new Path2D.Double();bolt.moveTo(36,6);bolt.lineTo(13,36);bolt.lineTo(29,36);
                        bolt.lineTo(25,58);bolt.lineTo(52,26);bolt.lineTo(35,26);bolt.closePath();g.fill(bolt);
                    }
                    case "target" -> {g.drawOval(7,7,50,50);g.drawOval(18,18,28,28);g.fillOval(27,27,10,10);}
                    case "computer" -> {
                        g.drawRoundRect(7,10,50,35,5,5);g.drawLine(32,46,32,55);g.drawLine(20,56,44,56);
                    }
                    default -> {
                        Path2D folder=new Path2D.Double();
                        folder.moveTo(5,18);folder.quadTo(5,13,10,13);
                        folder.lineTo(25,13);folder.lineTo(31,19);
                        folder.lineTo(54,19);folder.quadTo(59,19,59,24);
                        folder.lineTo(57,52);folder.quadTo(57,56,52,56);
                        folder.lineTo(10,56);folder.quadTo(5,56,5,51);folder.closePath();
                        g.fill(folder);
                    }
                }
        }
    }

    private static final class SleepingCat extends JComponent {
        SleepingCat() {
            setPreferredSize(new Dimension(220,145));
            setMaximumSize(new Dimension(220,145));
        }
        @Override protected void paintComponent(Graphics graphics) {
            Graphics2D g=(Graphics2D)graphics.create();
            try {
                g.scale(getWidth()/220d,getHeight()/145d);
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(new Color(0x8b7480));
                g.setStroke(new BasicStroke(2.5f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                Path2D loaf=new Path2D.Double();
                loaf.moveTo(34,108);loaf.curveTo(31,82,50,66,68,65);
                loaf.lineTo(72,49);loaf.lineTo(87,61);
                loaf.curveTo(104,58,125,58,140,62);
                loaf.lineTo(155,50);loaf.lineTo(159,69);
                loaf.curveTo(181,81,188,98,183,113);
                loaf.curveTo(179,126,155,129,111,129);
                loaf.curveTo(67,129,39,126,34,108);loaf.closePath();
                g.draw(loaf);
                g.drawArc(159,90,29,28,195,285);
                g.drawArc(76,82,17,9,190,155);
                g.drawArc(127,82,17,9,195,155);
                g.drawLine(108,96,112,99);g.drawLine(112,99,116,96);
                g.drawArc(77,113,22,10,185,160);
                g.drawArc(122,113,22,10,195,160);
                g.drawLine(61,138,160,138);
                g.setFont(LibraryDesign.font(Font.PLAIN,17));
                g.drawString("z",176,56);
            } finally {g.dispose();}
        }
    }

    private static final class DropOverlay extends LayerUI<JComponent> {
        final LibraryMoveHint hint=new LibraryMoveHint();
        boolean active;
        FlyMotion fly;
        LibrarySelectionDrag selection;
        private static final class FlyMotion {
            final BufferedImage image;
            final Point from,to;
            float progress;
            FlyMotion(BufferedImage image,Point from,Point to) {
                this.image=image;this.from=from;this.to=to;
            }
        }
        @Override public void paint(Graphics graphics,JComponent component) {
            super.paint(graphics,component);
            if(!active && fly==null && selection==null && !hint.visible())return;
            Graphics2D g=(Graphics2D)graphics.create();
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            if(active) {
                g.setColor(new Color(12,19,35,150));
                g.fillRect(0,0,component.getWidth(),component.getHeight());
                int x=component.getWidth()/2,y=component.getHeight()/2;
                g.setColor(Color.WHITE);
                g.setStroke(new BasicStroke(6,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
                g.drawLine(x-27,y,x+27,y);g.drawLine(x,y-27,x,y+27);
                g.setFont(g.getFont().deriveFont(Font.BOLD,18f));
                String instruction="PDF를 놓아 추가하기";
                g.drawString(instruction,x-g.getFontMetrics().stringWidth(instruction)/2,y+70);
            }
            if(fly!=null) {
                float p=fly.progress;
                float eased=p*p*(3f-2f*p);
                int x=Math.round(fly.from.x+(fly.to.x-fly.from.x)*eased);
                int y=Math.round(fly.from.y+(fly.to.y-fly.from.y)*eased);
                float scale=1f-.75f*p;
                int width=Math.max(1,Math.round(fly.image.getWidth()*scale));
                int height=Math.max(1,Math.round(fly.image.getHeight()*scale));
                g.setComposite(AlphaComposite.SrcOver.derive(1f-.85f*p));
                g.drawImage(fly.image,x-width/2,y-height/2,width,height,null);
            }
            if(selection!=null) {
                g.setComposite(AlphaComposite.SrcOver);
                selection.paint(g);
            }
            g.setComposite(AlphaComposite.SrcOver);hint.paint(g);
            g.dispose();
        }
    }

    private ImageIcon cover(PdfLibraryStore.Item item) {
        Path cached = item.source().getParent().resolve("cover-preview-v2.png");
        try {
            CoverVersion version=new CoverVersion(Files.getLastModifiedTime(item.source()).toMillis(),Files.size(item.source()),
                Files.isRegularFile(cached)?Files.getLastModifiedTime(cached).toMillis():-1);
            CachedCover ready=thumbnailCache.get(item.id());
            if(ready!=null&&version.equals(ready.version())&&pageCounts.getOrDefault(item.id(),0)>0)return ready.image();
            if(pageCounts.getOrDefault(item.id(),0)<=0)try {
                Properties metadata=new Properties();
                try(var input=Files.newInputStream(item.source().getParent().resolve("library.properties"))){metadata.load(input);}
                int count=Integer.parseInt(metadata.getProperty("pageCount","0"));if(count>0)pageCounts.put(item.id(),count);
            }catch(IOException|IllegalArgumentException ignored){/* Older documents are counted once off the UI thread. */}
            BufferedImage image=Files.isRegularFile(cached)?ImageIO.read(cached.toFile()):null;
            if (image==null || pageCounts.getOrDefault(item.id(),0)<=0) {
                boolean renderCover=image==null;
                try (PDDocument document = Loader.loadPDF(item.source().toFile())) {
                    pageCounts.put(item.id(),document.getNumberOfPages());
                    if(renderCover){
                        var box = document.getPage(0).getCropBox();
                        float scale = Math.min(2f, 600f / Math.max(1f,Math.max(box.getWidth(),box.getHeight())));
                        image = new PDFRenderer(document).renderImage(0, scale);
                    }
                }
                if (renderCover && image != null) ImageIO.write(image, "png", cached.toFile());
            }
            if (image == null) return null;
            // Retain source pixels for Retina painting; do not shrink and then enlarge the cover.
            ImageIcon icon=new ImageIcon(image);
            thumbnailCache.put(item.id(),new CachedCover(new CoverVersion(version.sourceModified(),version.sourceSize(),
                Files.isRegularFile(cached)?Files.getLastModifiedTime(cached).toMillis():-1),icon));
            return icon;
        } catch (Exception ignored) {pageCounts.putIfAbsent(item.id(),0);return null;}
    }

    @Override public void close() {
        searchDelay.stop();if(plannerView!=null)plannerView.dispose();
        assistantUi.closeUi();
        finishSelectionDrag();
        promotion.close();
        sectionMotion.cancel();
        revision++;hideDropOverlay.stop();folderHover.stop();folderBlink.stop();
        if(flyingTimer!=null){flyingTimer.stop();flyingTimer=null;}
        dropOverlay.fly=null;
        Runnable interrupted=flyingInterrupted;flyingCompletion=null;flyingInterrupted=null;if(interrupted!=null)interrupted.run();
        loader.shutdownNow();
    }
}
