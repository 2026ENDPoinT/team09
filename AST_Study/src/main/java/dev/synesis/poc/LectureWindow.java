package dev.synesis.poc;

import dev.synesis.poc.ui.StudyTheme;
import dev.synesis.poc.ui.MistWorkspaceTheme;

import javax.imageio.ImageIO;
import javax.swing.*;
import java.awt.*;
import java.awt.event.WindowAdapter;
import java.awt.event.WindowEvent;
import java.awt.event.ComponentAdapter;
import java.awt.event.ComponentEvent;
import java.awt.event.InputEvent;
import java.awt.event.KeyEvent;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.function.Consumer;
import javax.swing.filechooser.FileNameExtensionFilter;
import dev.synesis.poc.pdf.PdfWorkspace;

/** PDF study window used directly and by the AST bridge. */
final class LectureWindow {
    private static final Color WHITE = StudyTheme.PAPER, PRIMARY = StudyTheme.INK, SECONDARY = StudyTheme.MUTED;

    private final FullscreenFrame frame = new FullscreenFrame("AST 학습");
    private final JPanel root = new JPanel(new BorderLayout());
    private final Timer fullscreenLayoutTimer = new Timer(180, event -> refreshWindowLayout());
    private final Timer splitRatioTimer = new Timer(100, event -> {
        if(this.workspace.isShowing())this.pdfWorkspace.monitorStudyRatio(false);
    });
    private final Timer studyFontTimer = new Timer(750, event -> refreshStudyFonts());
    private StudyFontSettings appliedStudyFonts;

    private final MacFullscreenMouseFix fullscreenMouseFix = new MacFullscreenMouseFix(frame);
    private Object macFullscreenListener;
    private boolean restoreMaximizedAfterFullscreen;
    private final boolean automaticStudy;
    private PdfWorkspace pdfWorkspace;
    private final List<PdfWorkspace> backgroundWorkspaces = new ArrayList<>();
    private final List<CompletableFuture<Void>> closingWorkspaces = new ArrayList<>();
    private final CompletableFuture<Void> windowClosed = new CompletableFuture<>();
    private CompletableFuture<Void> shutdown = CompletableFuture.completedFuture(null);
    private boolean closingWindow;
    private boolean canShowStudyWindow;
    private final Set<PdfWorkspace> configuredWorkspaces = Collections.newSetFromMap(new IdentityHashMap<>());
    private JPanel workspaceNavigationBar;
    private JPanel learningNavigationComponent;
    private final JPanel workspaceRightControls=new JPanel(new FlowLayout(FlowLayout.RIGHT,8,12));
    private JComponent pdfVisibilityControl;
    private JPanel headerTitleRow;
    private final CardLayout screenLayout = new CardLayout();
    private final JPanel screens = new JPanel(screenLayout);
    private final JLayeredPane screenHost = new JLayeredPane() {
        @Override public void doLayout() {
            screens.setBounds(0,0,getWidth(),getHeight());
            floatingMentor.setBounds(0,56,getWidth(),Math.max(0,getHeight()-56));
            if(floatingMentor.isVisible())floatingMentor.doLayout();
        }
        @Override public boolean isOptimizedDrawingEnabled() {return false;}
        @Override public Component findComponentAt(int x,int y) {
            Point mentorPoint=SwingUtilities.convertPoint(this,x,y,floatingMentor);
            if(floatingMentor.isVisible()&&floatingMentor.contains(mentorPoint.x,mentorPoint.y)) {
                Component hit=SwingUtilities.getDeepestComponentAt(floatingMentor,mentorPoint.x,mentorPoint.y);
                return hit==null?floatingMentor:hit;
            }
            return super.findComponentAt(x,y);
        }
        @Override public Component getComponentAt(int x,int y) {
            Point mentorPoint=SwingUtilities.convertPoint(this,x,y,floatingMentor);
            if(floatingMentor.isVisible()&&floatingMentor.contains(mentorPoint.x,mentorPoint.y))return findComponentAt(x,y);
            return super.getComponentAt(x,y);
        }
    };
    private final dev.synesis.poc.ui.FloatingMentor floatingMentor=new dev.synesis.poc.ui.FloatingMentor();
    private final JToggleButton mentorToggle=floatingMentor.createNavigationToggle();
    private final JButton backgroundButton = new JButton("다른 문서");
    private final JLabel documentTitle = label("", 13, PRIMARY, Font.BOLD);
    private final java.util.Map<PdfWorkspace, Path> documentPaths = new IdentityHashMap<>();
    private final java.util.Map<PdfWorkspace, List<Consumer<String>>> pendingStudyOpens = new IdentityHashMap<>();
    private final JPanel studyActionRow = new JPanel(new BorderLayout());
    private final JButton displaySettingsButton = new JButton("⚙");
    private final JPanel workspace = new JPanel(new BorderLayout());
    private final JPanel documentContent = new JPanel(new BorderLayout());

    static void openStudy(Path pdf) {
        SwingUtilities.invokeLater(() -> {
            LectureWindow window = createStudyWindow(false);
            window.raiseStudyWindow();
            if(pdf!=null)window.openStudyPdf(pdf);
        });
    }

    static LectureWindow createStudyWindow(boolean automaticStudy) {
        UiFonts.install();
        LectureWindow window = new LectureWindow(automaticStudy);
        window.canShowStudyWindow=true;
        window.installQuitHandler();
        window.studyFontTimer.start();
        return window;
    }

    private void raiseStudyWindow() {
        if (!canShowStudyWindow || closingWindow || Boolean.getBoolean("ast.study.bridge.invisible")) return;
        if (!frame.isVisible()) {
            frame.setVisible(true);
            fullscreenMouseFix.install();
        }
        frame.setExtendedState(frame.getExtendedState() & ~Frame.ICONIFIED);
        frame.toFront();
    }

    CompletableFuture<Void> studyWindowClosed() { return windowClosed; }

    private void installQuitHandler() {
        if(!Desktop.isDesktopSupported())return;
        Desktop desktop=Desktop.getDesktop();
        if(desktop.isSupported(Desktop.Action.APP_QUIT_HANDLER))desktop.setQuitHandler((event,response)->{
            response.cancelQuit();
            SwingUtilities.invokeLater(()->frame.dispatchEvent(new WindowEvent(frame,WindowEvent.WINDOW_CLOSING)));
        });
    }

    PdfWorkspace studyWorkspace() { return pdfWorkspace; }

    static void renderPreview(Path path) throws Exception {
        Exception[] error = new Exception[1];
        LectureWindow[] created = new LectureWindow[1];
        SwingUtilities.invokeAndWait(() -> {
            try {
                UiFonts.install();
                created[0] = new LectureWindow();
            } catch (Exception failure) { error[0] = failure; }
        });
        if (error[0] != null) throw error[0];
        SwingUtilities.invokeAndWait(() -> {
            LectureWindow window = created[0];
            try {
                int previewWidth=Integer.getInteger("synesis.preview.width",1360);
                int previewHeight=Integer.getInteger("synesis.preview.height",850);
                window.root.setSize(previewWidth, previewHeight);
                if(Boolean.getBoolean("synesis.preview.workspace")) {
                    window.documentTitle.setText("학습 화면 미리보기");
                    String previewTab=System.getProperty("synesis.preview.tab","");
                    if(previewTab.equals("tutor") || "tutor".equals(System.getProperty("synesis.preview.sidepanel")))
                        window.pdfWorkspace.showTutor();
                    else if(previewTab.equals("concept"))window.pdfWorkspace.showConceptSummary();
                }
                layout(window.root);
                window.pdfWorkspace.refreshSidePanelLayout();
                layout(window.root);
                BufferedImage image = new BufferedImage(previewWidth, previewHeight, BufferedImage.TYPE_INT_RGB);
                Graphics2D graphics = image.createGraphics();
                window.root.printAll(graphics);
                graphics.dispose();
                Files.createDirectories(path.toAbsolutePath().getParent());
                ImageIO.write(image, "png", path.toFile());
            } catch (Exception failure) { error[0] = failure; }
            finally { window.closeWindow(); }
        });
        if (error[0] != null) throw error[0];
    }

    LectureWindow() {
        this(false);
    }

    private LectureWindow(boolean automaticStudy) {
        this.automaticStudy=automaticStudy;
        PdfWorkspace.DisplaySettings display=PdfWorkspace.displaySettings();
        appliedStudyFonts=new StudyFontSettings(display.summaryFont(),display.tutorFont());
        pdfWorkspace=createPdfWorkspace();
        fullscreenLayoutTimer.setRepeats(false);
        var icons = AppIcon.windowSizes();
        if (!icons.isEmpty()) frame.setIconImages(icons);
        frame.setDefaultCloseOperation(WindowConstants.DO_NOTHING_ON_CLOSE);
        frame.setMinimumSize(new Dimension(1120, 640));
        frame.setSize(1360, 850);
        frame.setLocationRelativeTo(null);
        frame.addWindowListener(new WindowAdapter() {
            @Override public void windowClosing(WindowEvent event) {
                closeWindow();
            }
        });
        frame.addComponentListener(new ComponentAdapter() {
            @Override public void componentResized(ComponentEvent event) {scheduleWindowLayoutRefresh();}
            @Override public void componentMoved(ComponentEvent event) {scheduleWindowLayoutRefresh();}
        });
        installWorkspaceListeners(pdfWorkspace);
        root.setBackground(StudyTheme.CANVAS);
        workspace.setBackground(StudyTheme.CANVAS);
        documentContent.setBackground(StudyTheme.CANVAS);
        documentContent.add(pdfWorkspace,BorderLayout.CENTER);
        workspace.add(MistWorkspaceTheme.shadows(documentContent),BorderLayout.CENTER);
        attachFloatingMentor();
        JPanel top = new JPanel(new BorderLayout());
        top.add(workspaceNavigation(),BorderLayout.NORTH);
        if(!automaticStudy) {
            studyActionRow.add(pdfWorkspace.studyActions(),BorderLayout.CENTER);
            top.add(studyActionRow,BorderLayout.SOUTH);
        }
        workspace.add(top,BorderLayout.NORTH);
        screens.add(workspace, "workspace");
        screenHost.add(screens,JLayeredPane.DEFAULT_LAYER);
        screenHost.add(floatingMentor,JLayeredPane.MODAL_LAYER);
        root.add(screenHost, BorderLayout.CENTER);
        frame.setContentPane(root);
        showWorkspace();
        JRootPane rootPane=frame.getRootPane();
        int shortcut=Toolkit.getDefaultToolkit().getMenuShortcutKeyMaskEx();
        rootPane.getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW)
            .put(KeyStroke.getKeyStroke(KeyEvent.VK_O,shortcut),"openPdf");
        rootPane.getActionMap().put("openPdf",new AbstractAction() {
            @Override public void actionPerformed(java.awt.event.ActionEvent event) { chooseStudyPdf(); }
        });
        if(System.getProperty("os.name", "").toLowerCase(Locale.ROOT).contains("mac")) {
            rootPane.getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW)
                .put(KeyStroke.getKeyStroke(KeyEvent.VK_M,InputEvent.META_DOWN_MASK),"minimizeWindow");
            rootPane.getActionMap().put("minimizeWindow",new AbstractAction() {
                @Override public void actionPerformed(java.awt.event.ActionEvent event) {
                    frame.setExtendedState(frame.getExtendedState() | Frame.ICONIFIED);
                }
            });
        }
        installMacFullscreenListener();
        splitRatioTimer.start();
    }

    private void installWorkspaceListeners(PdfWorkspace view) {
        if(!configuredWorkspaces.add(view))return;
        view.setPdfImportHandler(paths->{
            if(!paths.isEmpty())openStudyPdf(paths.getFirst());
        });
        view.setPdfOnlyScreenHandler(screen->{
            floatingMentor.setVisible(false);
            screens.add(screen,"pdf-only");screenLayout.show(screens,"pdf-only");
            screens.revalidate();screens.repaint();
        },()->{
            floatingMentor.setVisible(true);
            screenLayout.show(screens,"workspace");
            for(Component component:screens.getComponents())
                if(component!=workspace)screens.remove(component);
            screens.revalidate();screens.repaint();
        });
        view.addPropertyChangeListener(PdfWorkspace.PDF_OPENED_PROPERTY, event -> {
            if(view==pdfWorkspace) {
                updateDocumentTitle();
                showWorkspace();
                if(pendingStudyOpens.containsKey(view))raiseStudyWindow();
            }
            completeStudyOpens(view,null);
        });
        view.addPropertyChangeListener(PdfWorkspace.PDF_OPEN_FAILED_PROPERTY,event->{
            documentPaths.remove(view);
            completeStudyOpens(view,"pdf-open-failed");
            if(view!=pdfWorkspace) {
                backgroundWorkspaces.remove(view);
                configuredWorkspaces.remove(view);
                closeWorkspace(view);
            } else updateDocumentTitle();
            updateBackgroundButton();
        });
    }

    private void scheduleWindowLayoutRefresh() {
        if(frame.isDisplayable())fullscreenLayoutTimer.restart();
    }

    private void refreshWindowLayout() {
        if(!frame.isDisplayable())return;
        // Refresh after the native transition so Swing's bounds match the window.
        frame.invalidate();
        frame.validate();
        if(frame.isNativeFullscreen() && frame.isShowing()) {
            JRootPane pane=frame.getRootPane();
            AppDiagnostics.event("window.fullscreen.bounds",java.util.Map.of(
                "screen",frame.getGraphicsConfiguration().getBounds().toString(),
                "frame",frame.getBounds().toString(),"pane",pane.getBounds().toString(),
                "insets",frame.getInsets().toString(),"state",frame.getExtendedState()));
        }
        root.revalidate();
        root.repaint();
    }

    private void installMacFullscreenListener() {
        if(!System.getProperty("os.name", "").toLowerCase(java.util.Locale.ROOT).contains("mac"))return;
        try {
            Class<?> utilities=Class.forName("com.apple.eawt.FullScreenUtilities");
            Class<?> listener=Class.forName("com.apple.eawt.FullScreenListener");
            macFullscreenListener=Proxy.newProxyInstance(listener.getClassLoader(),new Class<?>[]{listener},
                (proxy,method,args)->{
                    if(method.getDeclaringClass()==Object.class)return switch(method.getName()) {
                        case "hashCode" -> System.identityHashCode(proxy);
                        case "equals" -> proxy==args[0];
                        default -> "SYNESIS fullscreen layout listener";
                    };
                    if(method.getName().equals("windowEnteringFullScreen")) {
                        SwingUtilities.invokeLater(()->{
                            Rectangle before=frame.getBounds();
                            int state=frame.getExtendedState();
                            restoreMaximizedAfterFullscreen=(state & Frame.MAXIMIZED_BOTH)==Frame.MAXIMIZED_BOTH;
                            if(restoreMaximizedAfterFullscreen && before.width-2>=frame.getMinimumSize().width) {
                                frame.setExtendedState(Frame.NORMAL);
                                frame.setBounds(before.x+1,before.y,before.width-2,before.height);
                                frame.validate();
                            }
                            AppDiagnostics.event("window.fullscreen.entering",java.util.Map.of(
                                "stateBefore",state,"before",before.toString(),
                                "after",frame.getBounds().toString(),
                                "restoreMaximized",restoreMaximizedAfterFullscreen));
                        });
                    } else if(method.getName().equals("windowEnteredFullScreen")) {
                        fullscreenMouseFix.setFullscreen(true);
                        SwingUtilities.invokeLater(()->{
                            frame.setNativeFullscreen(true);
                            scheduleWindowLayoutRefresh();
                        });
                    } else if(method.getName().equals("windowExitedFullScreen")) {
                        fullscreenMouseFix.setFullscreen(false);
                        SwingUtilities.invokeLater(()->{
                            frame.setNativeFullscreen(false);
                            scheduleWindowLayoutRefresh();
                            if(restoreMaximizedAfterFullscreen) {
                                restoreMaximizedAfterFullscreen=false;
                                frame.setExtendedState(Frame.MAXIMIZED_BOTH);
                            }
                        });
                    }
                    return null;
                });
            utilities.getMethod("addFullScreenListenerTo",Window.class,listener)
                .invoke(null,frame,macFullscreenListener);
        } catch(ReflectiveOperationException | RuntimeException ignored) {
            macFullscreenListener=null; // Resize events still trigger the layout refresh.
        }
    }

    private void removeMacFullscreenListener() {
        if(macFullscreenListener==null)return;
        try {
            Class<?> utilities=Class.forName("com.apple.eawt.FullScreenUtilities");
            Class<?> listener=Class.forName("com.apple.eawt.FullScreenListener");
            utilities.getMethod("removeFullScreenListenerFrom",Window.class,listener)
                .invoke(null,frame,macFullscreenListener);
        } catch(ReflectiveOperationException | RuntimeException ignored) { }
        macFullscreenListener=null;
    }

    private void chooseStudyPdf() {
        JFileChooser chooser=new JFileChooser();
        chooser.setDialogTitle("학습할 PDF 열기");
        chooser.setFileFilter(new FileNameExtensionFilter("PDF 문서 (*.pdf)","pdf"));
        if(chooser.showOpenDialog(frame)==JFileChooser.APPROVE_OPTION)openStudyPdf(chooser.getSelectedFile().toPath());
    }

    void openStudyPdf(Path path) {
        openStudyPdf(path,null,null);
    }

    private PdfWorkspace createPdfWorkspace() {
        return automaticStudy?PdfWorkspace.automaticStudy():new PdfWorkspace(false);
    }

    void openStudyPdf(Path path,String name,Consumer<String> result) {
        if(closingWindow) {
            if(result!=null)result.accept("closing");
            return;
        }
        Path file=path.toAbsolutePath().normalize();
        if(matchesDocument(pdfWorkspace,file)) {
            reopenStudyView(pdfWorkspace,name,result);
            return;
        }
        pdfWorkspace.closeOriginalOnlyView();
        PdfWorkspace opened=backgroundWorkspaces.stream().filter(view->matchesDocument(view,file)).findFirst().orElse(null);
        if(opened!=null) {
            showBackgroundWorkspace(opened);
            reopenStudyView(opened,name,result);
            return;
        }
        if(documentPaths.containsKey(pdfWorkspace))switchWorkspace(createPdfWorkspace());
        documentPaths.put(pdfWorkspace,file);
        setDocumentTitleName(name==null?file.getFileName().toString():name);
        showWorkspace();
        if(result!=null)pendingStudyOpens.computeIfAbsent(pdfWorkspace,key->new ArrayList<>()).add(result);
        if(name==null)pdfWorkspace.openPdf(file);
        else pdfWorkspace.openPdf(file,name);
    }

    private void reopenStudyView(PdfWorkspace view,String name,Consumer<String> result) {
        if(name!=null)view.setCurrentPdfDisplayName(name);
        updateDocumentTitle();
        if(view.currentPdfLocation()!=null) {
            raiseStudyWindow();
            if(result!=null)result.accept(null);
        } else if(result!=null) {
            pendingStudyOpens.computeIfAbsent(view,key->new ArrayList<>()).add(result);
        }
    }

    private void completeStudyOpens(PdfWorkspace view,String code) {
        var pending=pendingStudyOpens.remove(view);
        if(pending!=null)pending.forEach(result->result.accept(code));
    }

    private boolean matchesDocument(PdfWorkspace view,Path file) {
        return file.equals(documentPaths.get(view))||view.isCurrentPdf(file);
    }

    private void showBackgroundWorkspace(PdfWorkspace view) {
        if(!backgroundWorkspaces.remove(view))return;
        pdfWorkspace.closeOriginalOnlyView();
        switchWorkspace(view);
        showWorkspace();
        SwingUtilities.invokeLater(view::showPendingGenerationReport);
    }

    private void switchWorkspace(PdfWorkspace next) {
        floatingMentor.setOpen(false,false);
        PdfWorkspace old=pdfWorkspace;
        if(old!=next) {
            if(old.hasActiveStudyWork())backgroundWorkspaces.add(old);
            else {
                configuredWorkspaces.remove(old);
                documentPaths.remove(old);
                closeWorkspace(old);
            }
        }
        pdfWorkspace=next;
        installWorkspaceListeners(next);
        documentContent.removeAll();
        documentContent.add(next,BorderLayout.CENTER);
        if(!automaticStudy) {
            studyActionRow.removeAll();
            studyActionRow.add(next.studyActions(),BorderLayout.CENTER);
        }
        workspaceNavigationBar.remove(learningNavigationComponent);
        learningNavigationComponent=learningNavigation(next);
        workspaceNavigationBar.add(learningNavigationComponent,BorderLayout.CENTER);
        headerTitleRow.remove(pdfVisibilityControl);
        pdfVisibilityControl=next.movePdfToggle();
        pdfVisibilityControl.setFont(dev.synesis.poc.ui.LibraryDesign.medium(12));
        headerTitleRow.add(pdfVisibilityControl);
        attachFloatingMentor();
        updateDocumentTitle();
        workspaceNavigationBar.revalidate();
        updateBackgroundButton();
        workspace.revalidate();
        workspace.repaint();
    }

    private void showWorkspace() {
        floatingMentor.setVisible(true);
        screenLayout.show(screens, "workspace");
        workspaceNavigationBar.revalidate();
        root.revalidate();
    }

    private void updateBackgroundButton() {
        backgroundButton.setVisible(!backgroundWorkspaces.isEmpty());
    }

    private void showBackgroundDocuments() {
        JPopupMenu menu=new JPopupMenu();
        for(PdfWorkspace view:backgroundWorkspaces) {
            String name=view.currentPdfName();
            if(name.isEmpty()) {
                Path path=documentPaths.get(view);
                name=path==null?"PDF":path.getFileName().toString();
            }
            PdfWorkspace.GenerationProgress progress=view.generationProgress();
            JMenuItem item=new JMenuItem(progress==null?name:name+" · "+progress.stage());
            item.addActionListener(event->showBackgroundWorkspace(view));
            menu.add(item);
        }
        if(menu.getComponentCount()>0)menu.show(backgroundButton,0,backgroundButton.getHeight());
    }

    private void updateDocumentTitle() {
        String name=pdfWorkspace.currentPdfName();
        if(name.isEmpty()) {
            Path path=documentPaths.get(pdfWorkspace);
            if(path!=null)name=path.getFileName().toString();
        }
        setDocumentTitleName(name);
    }

    private void setDocumentTitleName(String name) {
        documentTitle.setText(name.length()>28?name.substring(0,25)+"…":name);
        documentTitle.setToolTipText(name);
    }

    private static void headerButton(AbstractButton button,boolean outlined) {
        MistWorkspaceTheme.button(button,outlined);
        button.setFont(dev.synesis.poc.ui.LibraryDesign.medium(12));
    }

    private JPanel documentNavigation() {
        JPanel title = new JPanel(new FlowLayout(FlowLayout.LEFT,12,12)){
            @Override public void doLayout(){
                if(pdfVisibilityControl==null||pdfVisibilityControl.getParent()!=this){super.doLayout();return;}
                Insets insets=getInsets();int x=insets.left,right=getWidth()-insets.right-12;
                for(Component child:getComponents())if(child.isVisible()&&child!=documentTitle&&child!=pdfVisibilityControl){
                    Dimension size=child.getPreferredSize();child.setBounds(x,(getHeight()-size.height)/2,size.width,size.height);x+=size.width+12;
                }
                Dimension button=pdfVisibilityControl.getPreferredSize();
                int nameWidth=Math.min(documentTitle.getPreferredSize().width,Math.max(0,right-x-button.width-12));
                documentTitle.setBounds(x,(getHeight()-28)/2,nameWidth,28);
                int buttonX=Math.max(insets.left,Math.min(x+nameWidth+12,right-button.width));
                pdfVisibilityControl.setBounds(buttonX,(getHeight()-button.height)/2,button.width,button.height);
            }
        };
        title.setBorder(BorderFactory.createEmptyBorder(0,16,0,0));
        title.setOpaque(false);
        if(!automaticStudy) {
            JButton choosePdf=new JButton("PDF 열기");
            headerButton(choosePdf,false);
            choosePdf.addActionListener(event->chooseStudyPdf());
            title.add(choosePdf);
        }
        documentTitle.setFont(dev.synesis.poc.ui.LibraryDesign.medium(14));
        documentTitle.setForeground(MistWorkspaceTheme.INK);
        title.add(documentTitle);
        return title;
    }

    private JPanel workspaceNavigation() {
        JPanel bar=new JPanel(new BorderLayout()){
            @Override public void doLayout(){
                int right=workspaceRightControls.getPreferredSize().width;
                int navWidth=Math.min(learningNavigationComponent.getPreferredSize().width,Math.max(120,getWidth()-right-300));
                int navX=Math.min((getWidth()-navWidth)/2,getWidth()-right-navWidth-12);
                if(headerTitleRow.getParent()==this)headerTitleRow.setBounds(0,0,Math.max(0,navX-12),56);
                learningNavigationComponent.setBounds(navX,8,navWidth,40);
                workspaceRightControls.setBounds(getWidth()-right,0,right,56);
            }
            @Override protected void paintBorder(Graphics graphics){
                Graphics2D g=(Graphics2D)graphics.create();try{g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setColor(Color.BLACK);g.fill(new java.awt.geom.Rectangle2D.Double(0,getHeight()-.1,getWidth(),.1));}finally{g.dispose();}
            }
        };
        workspaceNavigationBar=bar;
        headerTitleRow=documentNavigation();
        bar.add(headerTitleRow,BorderLayout.WEST);
        bar.setBackground(WHITE);
        bar.setPreferredSize(new Dimension(1,56));
        bar.setBorder(BorderFactory.createEmptyBorder());
        learningNavigationComponent=learningNavigation(pdfWorkspace);
        bar.add(learningNavigationComponent,BorderLayout.CENTER);
        MistWorkspaceTheme.button(displaySettingsButton,false);
        displaySettingsButton.setText("");displaySettingsButton.setIcon(MistWorkspaceTheme.icon("gear",16));
        displaySettingsButton.setPreferredSize(new Dimension(32,32));
        displaySettingsButton.setMinimumSize(new Dimension(32,32));
        displaySettingsButton.setMaximumSize(new Dimension(32,32));
        displaySettingsButton.setBorder(BorderFactory.createEmptyBorder());
        displaySettingsButton.setFont(StudyTheme.font(Font.PLAIN,25));
        displaySettingsButton.setToolTipText("화면 설정");
        displaySettingsButton.addActionListener(event->showDisplaySettings());
        JPanel right=workspaceRightControls;right.setOpaque(false);
        right.setBorder(BorderFactory.createEmptyBorder(0,0,0,20));
        pdfVisibilityControl=pdfWorkspace.movePdfToggle();
        pdfVisibilityControl.setFont(dev.synesis.poc.ui.LibraryDesign.medium(12));
        headerTitleRow.add(pdfVisibilityControl);
        headerButton(backgroundButton,false);
        backgroundButton.addActionListener(event->showBackgroundDocuments());
        right.add(backgroundButton);
        updateBackgroundButton();
        right.add(displaySettingsButton);
        bar.add(right,BorderLayout.EAST);
        return bar;
    }

    private JPanel learningNavigation(PdfWorkspace view){
        JPanel navigation=view.moveLearningNavigation();
        navigation.add(mentorToggle,BorderLayout.EAST);
        return navigation;
    }

    private void attachFloatingMentor() {
        floatingMentor.setContent(pdfWorkspace.moveTutorToSidePanel(
            ()->floatingMentor.setOpen(true),()->floatingMentor.setOpen(false)));
    }

    private void closeWorkspace(PdfWorkspace view) {
        closingWorkspaces.removeIf(CompletableFuture::isDone);
        closingWorkspaces.add(view.closeAndAwait().whenComplete((ignored,failure)->{
            if(failure!=null)AppDiagnostics.error("study.shutdown",failure,java.util.Map.of());
        }));
    }

    CompletableFuture<Void> closeWindow() {
        if(closingWindow)return shutdown;
        closingWindow=true;
        for(PdfWorkspace view:List.copyOf(pendingStudyOpens.keySet()))completeStudyOpens(view,"closing");
        floatingMentor.close();
        closeWorkspace(pdfWorkspace);
        backgroundWorkspaces.forEach(this::closeWorkspace);
        backgroundWorkspaces.clear();
        shutdown=CompletableFuture.allOf(closingWorkspaces.toArray(CompletableFuture[]::new));
        CompletableFuture<Void> allClosed=shutdown;
        // Keep the JVM alive while the workers finish saving or settling a cancelled request.
        if(!allClosed.isDone())Thread.ofPlatform().name("ast-study-shutdown").start(()->{
            allClosed.handle((ignored,failure)->null).join();
        });
        fullscreenLayoutTimer.stop(); splitRatioTimer.stop(); studyFontTimer.stop();
        fullscreenMouseFix.close(); removeMacFullscreenListener();
        frame.dispose();
        allClosed.whenComplete((ignored,failure)->{
            if(failure==null)windowClosed.complete(null);
            else windowClosed.completeExceptionally(failure);
        });
        return allClosed;
    }

    private void refreshStudyFonts() {
        StudyFontSettings fonts;
        try {
            fonts=StudyFontSettings.read(PdfWorkspace.legacyStudyFonts());
        } catch (IOException unavailable) {
            return;
        }
        if (fonts.equals(appliedStudyFonts)) return;
        pdfWorkspace.applyStudyFonts(appliedStudyFonts,fonts);
        for (PdfWorkspace workspace:backgroundWorkspaces) workspace.applyStudyFonts(appliedStudyFonts,fonts);
        appliedStudyFonts=fonts;
    }

    private void showDisplaySettings() {
        PdfWorkspace.DisplaySettings current=PdfWorkspace.displaySettings();
        JPanel form=new JPanel();
        form.setLayout(new BoxLayout(form,BoxLayout.Y_AXIS));
        form.setBackground(WHITE);
        form.setBorder(BorderFactory.createEmptyBorder(14,18,14,18));
        form.setPreferredSize(new Dimension(420,287));
        JLabel qualityLabel=label("PDF 표시 화질",13,PRIMARY,Font.BOLD);
        qualityLabel.setAlignmentX(Component.LEFT_ALIGNMENT);
        form.add(qualityLabel);
        form.add(Box.createVerticalStrut(7));
        JComboBox<String> quality=new JComboBox<>(new String[]{"저화질","일반","고화질"});
        quality.setSelectedItem(current.pdfQuality());
        StudyTheme.comboBox(quality);
        quality.setMaximumSize(new Dimension(Integer.MAX_VALUE,36));
        quality.setAlignmentX(Component.LEFT_ALIGNMENT);
        form.add(quality);
        form.add(Box.createVerticalStrut(18));
        JLabel fontLabel=label("기본 글자 크기",13,PRIMARY,Font.BOLD);
        fontLabel.setAlignmentX(Component.LEFT_ALIGNMENT);
        form.add(fontLabel);
        form.add(Box.createVerticalStrut(7));
        JSlider summarySize=displayFontSlider(form,"강의 해설",current.summaryFont(),"px");
        JSlider conceptSize=displayFontSlider(form,"개념 정리",current.conceptFont(),"pt");
        JSlider tutorSize=displayFontSlider(form,"AI멘토",current.tutorFont(),"px");
        JSlider quizSize=displayFontSlider(form,"N제",current.quizFont(),"pt");
        int answer=JOptionPane.showOptionDialog(frame,form,"화면 설정",
            JOptionPane.DEFAULT_OPTION,JOptionPane.PLAIN_MESSAGE,null,
            new Object[]{"저장","취소"},"저장");
        if(answer!=0)return;
        PdfWorkspace.DisplaySettings selected=new PdfWorkspace.DisplaySettings(
            (String)quality.getSelectedItem(),summarySize.getValue(),conceptSize.getValue(),tutorSize.getValue(),quizSize.getValue());
        try {
            PdfWorkspace.saveDisplaySettings(selected);
        } catch (IOException | IllegalStateException failure) {
            JOptionPane.showMessageDialog(frame,"화면 설정을 저장하지 못했어요.","화면 설정",JOptionPane.ERROR_MESSAGE);
            return;
        }
        appliedStudyFonts=new StudyFontSettings(selected.summaryFont(),selected.tutorFont());
        pdfWorkspace.applyDisplaySettings(selected);
        for(PdfWorkspace workspace:backgroundWorkspaces)workspace.applyDisplaySettings(selected);
    }

    private static JSlider displayFontSlider(JPanel form,String name,int value,String unit) {
        JPanel row=new JPanel(new BorderLayout(12,0));
        row.setOpaque(false);
        row.setMaximumSize(new Dimension(Integer.MAX_VALUE,42));
        row.setAlignmentX(Component.LEFT_ALIGNMENT);
        JLabel title=label(name,12,PRIMARY,Font.PLAIN);
        title.setPreferredSize(new Dimension(56,26));
        row.add(title,BorderLayout.WEST);
        JSlider slider=new JSlider(StudyFontSettings.MIN,StudyFontSettings.MAX,value);
        slider.setBackground(WHITE);
        row.add(slider,BorderLayout.CENTER);
        JLabel amount=label(value+unit,12,SECONDARY,Font.PLAIN);
        amount.setPreferredSize(new Dimension(36,26));
        slider.addChangeListener(event->amount.setText(slider.getValue()+unit));
        row.add(amount,BorderLayout.EAST);
        form.add(row);
        return slider;
    }

    private static JLabel label(String value, int size, Color color, int style) {
        JLabel label = new JLabel(value);
        label.setFont(new Font(UiFonts.FAMILY, style, size));
        label.setForeground(color);
        return label;
    }

    private static void layout(Container component) {
        component.doLayout();
        for (Component child : component.getComponents())
            if (child instanceof Container container) layout(container);
    }

}

/** In native fullscreen, preserve the menu-bar inset while filling the bottom edge. */
final class FullscreenFrame extends JFrame {
    private boolean nativeFullscreen;

    FullscreenFrame(String title) { super(title); }

    void setNativeFullscreen(boolean value) { nativeFullscreen=value; }

    boolean isNativeFullscreen() { return nativeFullscreen; }

    int peerTitleBarInset() { return super.getInsets().top; }

    @Override public Insets getInsets() {
        Insets insets=super.getInsets();
        return nativeFullscreen ? new Insets(insets.top,insets.left,0,insets.right) : insets;
    }
}
