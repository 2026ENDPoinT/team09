package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.*;
import dev.synesis.poc.ui.*;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import javax.swing.filechooser.FileNameExtensionFilter;
import java.awt.*;
import java.awt.event.*;
import java.nio.file.*;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.*;

/** An independent PDF-only entry point. Never constructs the recording or planner shell. */
public final class WindowsPdfTrial extends JPanel implements AutoCloseable {
    private final PdfWorkspace workspace = new PdfWorkspace(true);
    private final JLabel document = new JLabel("PDF를 열어 공부를 시작해요");
    private final JLabel progress = new JLabel(" ");
    private final ExecutorService files = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r,"trial-files");t.setDaemon(true);return t;
    });

    WindowsPdfTrial() {
        super(new BorderLayout());setBackground(Color.WHITE);
        JPanel bar = new JPanel(new BorderLayout(18,0));bar.setBackground(Color.WHITE);
        bar.setBorder(new EmptyBorder(12,18,12,18));
        JPanel tools=new JPanel(new FlowLayout(FlowLayout.LEFT,10,0));tools.setOpaque(false);
        tools.add(new JLabel(BrandLogo.wordmark(110)));
        tools.add(button("PDF 열기",this::choosePdf));tools.add(button("내 문서",this::showLibrary));
        bar.add(tools,BorderLayout.WEST);
        document.setFont(StudyTheme.font(Font.PLAIN,13));document.setForeground(StudyTheme.MUTED);
        bar.add(document,BorderLayout.CENTER);
        bar.add(button("시험 크레딧 추가",this::refillCredits),BorderLayout.EAST);
        add(bar,BorderLayout.NORTH);add(workspace,BorderLayout.CENTER);
        progress.setFont(StudyTheme.font(Font.PLAIN,12));progress.setForeground(StudyTheme.MUTED);
        progress.setBorder(new EmptyBorder(6,18,8,18));add(progress,BorderLayout.SOUTH);
        // Keep the existing PDF/summary/concept/tutor implementation and its scroll behavior.
        // Unavailable trial features are removed once, before this view becomes visible.
        restrictControls(workspace);
        workspace.setPdfImportHandler(paths->{if(!paths.isEmpty())open(paths.getFirst());});
        workspace.addPropertyChangeListener(PdfWorkspace.PDF_OPENED_PROPERTY,e->{
            document.setText(workspace.currentPdfName());document.setToolTipText(workspace.currentPdfName());
        });
        workspace.addPropertyChangeListener(PdfWorkspace.GENERATION_PROGRESS_PROPERTY,e->{
            PdfWorkspace.GenerationProgress p=workspace.generationProgress();
            progress.setText(p==null?" ":p.stage()+" · "+p.percent()+"%");
        });
        getInputMap(WHEN_ANCESTOR_OF_FOCUSED_COMPONENT).put(KeyStroke.getKeyStroke(KeyEvent.VK_O,InputEvent.CTRL_DOWN_MASK),"open");
        getActionMap().put("open",new AbstractAction(){public void actionPerformed(ActionEvent e){choosePdf();}});
    }

    private static JButton button(String title,Runnable action) {
        JButton b=new JButton(title);StudyTheme.button(b,false);b.addActionListener(e->action.run());return b;
    }
    private static void restrictControls(Container parent) {
        for(Component c:parent.getComponents()) {
            if(c instanceof AbstractButton b && "퀴즈".equals(b.getText())) {
                b.setSelected(false);b.setEnabled(false);b.setVisible(false);
            }
            if(c instanceof Container nested)restrictControls(nested);
        }
    }
    private void choosePdf() {
        JFileChooser chooser=new JFileChooser();chooser.setDialogTitle("공부할 PDF를 선택해 주세요");
        chooser.setFileFilter(new FileNameExtensionFilter("PDF 문서 (*.pdf)","pdf"));
        if(chooser.showOpenDialog(this)==JFileChooser.APPROVE_OPTION)open(chooser.getSelectedFile().toPath());
    }
    private void open(Path path) {
        if(workspace.generationProgress()!=null&&!workspace.generationProgress().finished()) {
            int result=JOptionPane.showConfirmDialog(this,"진행 중인 분석을 중단하고 다른 PDF를 열까요?\n이미 전송된 AI 요청에는 사용료가 발생할 수 있어요.","PDF 열기",JOptionPane.YES_NO_OPTION);
            if(result!=JOptionPane.YES_OPTION)return;
        }
        workspace.openPdf(path);
    }
    private void showLibrary() {
        files.execute(()->{
            try {
                List<PdfLibraryStore.Item> items=PdfLibraryStore.list(AppPaths.library());
                SwingUtilities.invokeLater(()->{
                    if(items.isEmpty()){JOptionPane.showMessageDialog(this,"저장된 PDF가 없어요. [PDF 열기]로 문서를 추가해 주세요.");return;}
                    JList<PdfLibraryStore.Item> list=new JList<>(items.toArray(PdfLibraryStore.Item[]::new));
                    list.setSelectionMode(ListSelectionModel.SINGLE_SELECTION);list.setSelectedIndex(0);
                    list.setFixedCellHeight(42);list.setFont(StudyTheme.font(Font.PLAIN,14));
                    list.setCellRenderer((view,item,index,selected,focus)->{
                        JLabel l=new JLabel(item.name());l.setOpaque(true);l.setBorder(new EmptyBorder(8,12,8,12));
                        l.setBackground(selected?StudyTheme.ACCENT:Color.WHITE);l.setForeground(selected?Color.WHITE:StudyTheme.INK);return l;
                    });
                    JScrollPane pane=new JScrollPane(list);pane.setPreferredSize(new Dimension(480,320));
                    if(JOptionPane.showConfirmDialog(this,pane,"내 문서",JOptionPane.OK_CANCEL_OPTION,JOptionPane.PLAIN_MESSAGE)==JOptionPane.OK_OPTION&&list.getSelectedValue()!=null)open(list.getSelectedValue().source());
                });
            }catch(Exception error){SwingUtilities.invokeLater(()->JOptionPane.showMessageDialog(this,"저장된 문서 목록을 읽지 못했어요.","내 문서",JOptionPane.ERROR_MESSAGE));}
        });
    }
    private void refillCredits() {
        int result=JOptionPane.showConfirmDialog(this,"시험용 크레딧 2,700개를 추가할까요?\n앱 안의 크레딧만 추가되며, AI 실제 사용료는 제공자 계정에 별도로 청구돼요.","시험 크레딧",JOptionPane.YES_NO_OPTION);
        if(result!=JOptionPane.YES_OPTION)return;
        files.execute(()->{try{CreditWallet.topUp(AppPaths.library(),CreditWallet.PLANS[0]);SwingUtilities.invokeLater(()->JOptionPane.showMessageDialog(this,"시험 크레딧을 추가했어요."));}
            catch(Exception error){SwingUtilities.invokeLater(()->JOptionPane.showMessageDialog(this,"크레딧을 추가하지 못했어요. 잠시 뒤 다시 시도해 주세요."));}});
    }
    static void prepareStore() throws Exception {
        Path root=AppPaths.dataRoot();Files.createDirectories(root);
        if(!Files.exists(root.resolve("manifest.json"))) {
            JsonObject manifest=new JsonObject();manifest.addProperty("format","synesis-user-data");manifest.addProperty("version",1);
            manifest.addProperty("storeId",UUID.randomUUID().toString());manifest.addProperty("createdAtMs",System.currentTimeMillis());
            Files.writeString(root.resolve("manifest.json"),new Gson().toJson(manifest),StandardOpenOption.CREATE_NEW);
        }
        AppPaths.prepare();
        CreditWallet.read(AppPaths.library(),0);
        CreditWallet.activateBilling(AppPaths.library(),0);
        Path marker=AppPaths.account().resolve("windows-pdf-trial-initialized");
        if(!Files.exists(marker)) {
            CreditWallet.topUp(AppPaths.library(),CreditWallet.PLANS[0]);
            Files.writeString(marker,"trial-v1",StandardOpenOption.CREATE_NEW);
        }
    }
    @Override public void close(){workspace.close();files.shutdownNow();}
    public static void main(String[] args) {
        try {
            prepareStore();AppDiagnostics.install();TrialUi.install();
            if(args.length>0&&args[0].equals("--check")) {
                SwingUtilities.invokeAndWait(()->{
                    try(WindowsPdfTrial content=new WindowsPdfTrial()) {
                        content.setSize(1100,720);content.doLayout();
                        if(content.workspace.getWidth()<=0)throw new AssertionError("PDF workspace has no width");
                        checkTrialControls(content);
                    }
                });
                if(args.length>1)try(var doc=org.apache.pdfbox.Loader.loadPDF(Path.of(args[1]).toFile())) {
                    var image=new org.apache.pdfbox.rendering.PDFRenderer(doc).renderImage(0);
                    if(image.getWidth()<1)throw new AssertionError("PDF render failed");
                }
                System.out.println("Java PDF/tutor view, fonts and PDFBox checks passed. No API request made.");
                System.exit(0);
            }
            SwingUtilities.invokeLater(()->{
                try {
                    WindowsPdfTrial content=new WindowsPdfTrial();JFrame frame=new JFrame("SYNESIS · PDF & AI멘토 · Windows 시험판");
                    frame.setDefaultCloseOperation(WindowConstants.DO_NOTHING_ON_CLOSE);frame.setContentPane(content);
                    Rectangle screen=GraphicsEnvironment.getLocalGraphicsEnvironment().getMaximumWindowBounds();
                    frame.setMinimumSize(new Dimension(Math.min(900,screen.width),Math.min(580,screen.height)));
                    frame.setSize(Math.min(1360,screen.width),Math.min(850,screen.height));frame.setLocationRelativeTo(null);
                    frame.addWindowListener(new WindowAdapter(){public void windowClosing(WindowEvent e){
                        PdfWorkspace.GenerationProgress p=content.workspace.generationProgress();
                        if(p!=null&&!p.finished()&&JOptionPane.showConfirmDialog(frame,"분석을 중단하고 종료할까요?\n완료된 결과는 저장돼요. 이미 전송된 요청에는 사용료가 발생할 수 있어요.","종료",JOptionPane.YES_NO_OPTION)!=JOptionPane.YES_OPTION)return;
                        content.close();frame.dispose();System.exit(0);
                    }});
                    frame.setVisible(true);
                }catch(Throwable error){startupError();System.exit(1);}
            });
        }catch(Throwable error){
            if(args.length>0&&args[0].equals("--check")) {
                Throwable cause=error;while(cause.getCause()!=null)cause=cause.getCause();
                System.err.println("Java runtime check failed: "+cause.getClass().getSimpleName());
            } else startupError();
            System.exit(1);
        }
    }
    private static void checkTrialControls(Container parent) {
        for(Component c:parent.getComponents()) {
            if(c instanceof AbstractButton b&&"퀴즈".equals(b.getText())&&b.isVisible())
                throw new AssertionError("Unavailable trial control is visible");
            if(c instanceof Container nested)checkTrialControls(nested);
        }
    }
    private static void startupError(){JOptionPane.showMessageDialog(null,"SYNESIS를 시작하지 못했어요.\n압축을 모두 풀었는지 확인하고, [SYNESIS-CHECK.cmd]로 실행 상태를 확인해 주세요.","SYNESIS",JOptionPane.ERROR_MESSAGE);}
}
