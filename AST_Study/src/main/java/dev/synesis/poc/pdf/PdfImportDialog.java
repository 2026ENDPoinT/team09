package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.LibraryDesign;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.rendering.PDFRenderer;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import javax.swing.tree.DefaultMutableTreeNode;
import javax.swing.tree.TreePath;
import java.awt.*;
import java.awt.event.*;
import java.nio.file.Path;
import java.util.List;

/** Read-only staging: no library copy, metadata write or paid work before confirmation. */
public final class PdfImportDialog extends JDialog {
    private static final class Entry {
        final Path file;
        String destination="", error;
        boolean autoGenerate=true;
        String strategy=PdfStudyStrategy.DEFAULT;
        volatile boolean ready;
        int pages;
        ImageIcon cover;
        PdfImportExisting.Saved saved;
        String lookupError;
        Entry(Path file){this.file=file;}
        @Override public String toString(){return file.getFileName().toString();}
    }
    private record Folder(String id,String label) {
        @Override public String toString(){return label;}
    }
    private final List<Entry> entries;
    private final JList<Entry> files;
    private final JLabel preview=new JLabel("미리보기 준비 중…",SwingConstants.CENTER);
    private final JLabel title=new JLabel(), pages=new JLabel(" ");
    private final JTextArea existing=new JTextArea();
    private final JCheckBox automatic=new JCheckBox("자동 강의해설 / 개념 정리 생성하기",true);
    private final JComboBox<String> engine=new JComboBox<>(PdfStudyStrategy.ENGINE_LABELS);
    private final JTree locations;
    private final JButton confirm=new JButton("불러오기");
    private final JLabel status=new JLabel("파일을 확인하고 있어요…");
    private boolean switching, accepted;
    private SwingWorker<Void,Entry> worker;

    public static List<PdfBatchQueue.ImportChoice> show(Component owner,List<Path> paths) {
        List<Path> selected=paths.stream().filter(java.util.Objects::nonNull)
            .map(p->p.toAbsolutePath().normalize()).distinct().toList();
        if(selected.isEmpty())return List.of();
        try {
            PdfImportDialog dialog=new PdfImportDialog(owner instanceof Window w?w:SwingUtilities.getWindowAncestor(owner),selected,
                PdfLibraryOrganization.load(PdfLibraryStore.defaultRoot()));
            dialog.setVisible(true);
            return dialog.accepted?dialog.entries.stream().map(e->new PdfBatchQueue.ImportChoice(e.file,e.destination,e.autoGenerate,e.strategy)).toList():List.of();
        } catch(Exception error) {
            JOptionPane.showMessageDialog(owner,"불러오기 창을 열지 못했어요.\n"+error.getMessage(),"PDF 불러오기",JOptionPane.ERROR_MESSAGE);
            return List.of();
        }
    }

    private PdfImportDialog(Window owner,List<Path> paths,PdfLibraryOrganization organization) {
        super(owner,"PDF 불러오기",ModalityType.APPLICATION_MODAL);
        entries=paths.stream().map(Entry::new).toList();
        setDefaultCloseOperation(DISPOSE_ON_CLOSE);
        JPanel content=new JPanel(new BorderLayout(20,20));content.setBackground(Color.WHITE);
        content.setBorder(new EmptyBorder(24,24,20,24));setContentPane(content);
        JLabel heading=new JLabel("PDF 불러오기");heading.setFont(LibraryDesign.font(Font.BOLD,22));content.add(heading,BorderLayout.NORTH);
        files=new JList<>(entries.toArray(Entry[]::new));files.setSelectionMode(ListSelectionModel.SINGLE_SELECTION);
        files.setFixedCellHeight(44);files.setFont(LibraryDesign.medium(13));
        files.addListSelectionListener(e->{if(!e.getValueIsAdjusting())displaySelected();});
        JPanel center=new JPanel(new BorderLayout(20,0));center.setOpaque(false);
        if(entries.size()>1) {
            JScrollPane listScroll=new JScrollPane(files);listScroll.setPreferredSize(new Dimension(200,380));center.add(listScroll,BorderLayout.WEST);
        }
        JPanel details=new JPanel(new BorderLayout(0,12));details.setOpaque(false);
        preview.setPreferredSize(new Dimension(260,300));preview.setOpaque(true);preview.setBackground(new Color(0xf5f6f8));
        preview.setBorder(BorderFactory.createLineBorder(LibraryDesign.LINE));details.add(preview,BorderLayout.CENTER);
        JPanel labels=new JPanel(new GridLayout(0,1,0,6));labels.setOpaque(false);
        title.setFont(LibraryDesign.medium(14));pages.setForeground(LibraryDesign.MUTED);labels.add(title);labels.add(pages);details.add(labels,BorderLayout.SOUTH);
        center.add(details,BorderLayout.CENTER);
        DefaultMutableTreeNode root=new DefaultMutableTreeNode(new Folder("","내 문서 · 홈 화면"));
        addFolders(root,"",organization,new java.util.HashSet<>());
        locations=new JTree(root);locations.setFont(LibraryDesign.medium(13));locations.setRowHeight(32);
        locations.getSelectionModel().setSelectionMode(javax.swing.tree.TreeSelectionModel.SINGLE_TREE_SELECTION);
        locations.addTreeSelectionListener(e->{
            if(switching || files.getSelectedValue()==null)return;
            var node=(DefaultMutableTreeNode)locations.getLastSelectedPathComponent();
            if(node!=null)files.getSelectedValue().destination=((Folder)node.getUserObject()).id();
        });
        JPanel settings=new JPanel(new BorderLayout(0,12));settings.setOpaque(false);settings.setPreferredSize(new Dimension(330,380));
        JLabel locationLabel=new JLabel("불러올 위치");locationLabel.setFont(LibraryDesign.medium(15));
        existing.setEditable(false);existing.setLineWrap(true);existing.setWrapStyleWord(true);
        existing.setFont(LibraryDesign.font(Font.PLAIN,13));existing.setForeground(LibraryDesign.INK);
        existing.setBackground(new Color(0xf5f6f8));existing.setBorder(new EmptyBorder(12,12,12,12));existing.setVisible(false);
        JPanel settingsHeading=new JPanel(new BorderLayout(0,12));settingsHeading.setOpaque(false);
        settingsHeading.add(existing,BorderLayout.NORTH);settingsHeading.add(locationLabel,BorderLayout.SOUTH);
        settings.add(settingsHeading,BorderLayout.NORTH);
        settings.add(new JScrollPane(locations),BorderLayout.CENTER);
        automatic.setOpaque(false);automatic.setFont(LibraryDesign.medium(13));automatic.addActionListener(e->{if(!switching && files.getSelectedValue()!=null)files.getSelectedValue().autoGenerate=automatic.isSelected();});
        JPanel generationSettings=new JPanel(new GridLayout(0,1,0,8));generationSettings.setOpaque(false);
        generationSettings.add(automatic);generationSettings.add(new JLabel("생성 엔진"));generationSettings.add(engine);
        engine.addActionListener(e->{if(!switching && files.getSelectedValue()!=null)files.getSelectedValue().strategy=PdfStudyStrategy.ENGINE_IDS[engine.getSelectedIndex()];});
        settings.add(generationSettings,BorderLayout.SOUTH);center.add(settings,BorderLayout.EAST);content.add(center,BorderLayout.CENTER);
        JPanel footer=new JPanel(new BorderLayout(12,0));footer.setOpaque(false);status.setFont(LibraryDesign.font(Font.PLAIN,12));footer.add(status,BorderLayout.CENTER);
        JPanel buttons=new JPanel(new FlowLayout(FlowLayout.RIGHT,8,0));buttons.setOpaque(false);
        JButton cancel=new JButton("취소");LibraryDesign.button(cancel,false);LibraryDesign.button(confirm,true);
        cancel.setPreferredSize(new Dimension(84,40));confirm.setPreferredSize(new Dimension(110,40));
        cancel.addActionListener(e->dispose());confirm.setEnabled(false);
        confirm.addActionListener(e->{if(entries.stream().allMatch(x->x.ready && x.error==null)){accepted=true;dispose();}});
        buttons.add(cancel);buttons.add(confirm);footer.add(buttons,BorderLayout.EAST);content.add(footer,BorderLayout.SOUTH);
        getRootPane().setDefaultButton(confirm);
        getRootPane().registerKeyboardAction(e->dispose(),KeyStroke.getKeyStroke(KeyEvent.VK_ESCAPE,0),JComponent.WHEN_IN_FOCUSED_WINDOW);
        addWindowListener(new WindowAdapter(){@Override public void windowClosed(WindowEvent e){if(worker!=null)worker.cancel(true);}});
        files.setSelectedIndex(0);setMinimumSize(new Dimension(entries.size()>1?1040:820,550));pack();setLocationRelativeTo(owner);
        loadPreviews();
    }

    private static void addFolders(DefaultMutableTreeNode parent,String id,PdfLibraryOrganization organization,java.util.Set<String> seen) {
        for(var folder:organization.folders())if(folder.parentId().equals(id) && !organization.isFolderInTrash(folder.id()) && seen.add(folder.id())) {
            DefaultMutableTreeNode node=new DefaultMutableTreeNode(new Folder(folder.id(),folder.name()));parent.add(node);
            addFolders(node,folder.id(),organization,seen);
        }
    }
    private void displaySelected() {
        Entry entry=files.getSelectedValue();if(entry==null)return;
        switching=true;
        try {
            title.setText(entry.toString());title.setToolTipText(entry.toString());
            preview.setIcon(entry.cover);preview.setText(entry.error!=null?"미리보기를 열지 못했어요":entry.ready?"":"미리보기 준비 중…");
            pages.setText(entry.error!=null?entry.error:entry.ready?entry.pages+"쪽":"쪽수 확인 중…");
            pages.setToolTipText(entry.error);automatic.setSelected(entry.autoGenerate);
            engine.setSelectedIndex(java.util.Arrays.asList(PdfStudyStrategy.ENGINE_IDS).indexOf(entry.strategy));
            existing.setText(entry.saved!=null?entry.saved.message():entry.lookupError==null?"":entry.lookupError);
            existing.setVisible(entry.saved!=null || entry.lookupError!=null);
            var nodes=((DefaultMutableTreeNode)locations.getModel().getRoot()).depthFirstEnumeration();
            while(nodes.hasMoreElements()) {
                var node=(DefaultMutableTreeNode)nodes.nextElement();
                if(((Folder)node.getUserObject()).id().equals(entry.destination)) {
                    TreePath path=new TreePath(node.getPath());locations.setSelectionPath(path);locations.scrollPathToVisible(path);break;
                }
            }
        } finally {switching=false;}
    }
    private void loadPreviews() {
        worker=new SwingWorker<>() {
            @Override protected Void doInBackground() {
                for(Entry entry:entries) {
                    if(isCancelled())break;
                    try(var document=Loader.loadPDF(entry.file.toFile())) {
                        entry.pages=document.getNumberOfPages();
                        if(entry.pages==0)throw new java.io.IOException("빈 PDF예요.");
                        var box=document.getPage(0).getCropBox();
                        float scale=Math.min(260f/Math.max(1,box.getWidth()),300f/Math.max(1,box.getHeight()));
                        var renderer=new PDFRenderer(document);renderer.setSubsamplingAllowed(true);
                        entry.cover=new ImageIcon(renderer.renderImage(0,scale));
                    } catch(Exception error){entry.error="PDF를 읽을 수 없어요. 파일을 확인해 주세요.";}
                    if(isCancelled())break;
                    if(entry.error==null)try {entry.saved=PdfImportExisting.find(entry.file,PdfLibraryStore.defaultRoot());}
                    catch(Exception error){entry.lookupError="기존 저장 여부를 확인하지 못했어요.";}
                    entry.ready=true;publish(entry);
                }
                return null;
            }
            @Override protected void process(List<Entry> updated) {
                if(!isDisplayable())return;
                displaySelected();files.repaint();
                long ready=entries.stream().filter(e->e.ready).count();
                boolean valid=entries.stream().allMatch(e->e.ready && e.error==null);
                confirm.setEnabled(valid);
                status.setText(valid?entries.size()+"개 파일 · 파일별 위치와 자동 생성 여부를 설정해 주세요.":
                    entries.stream().anyMatch(e->e.error!=null)?"읽을 수 없는 파일이 있어요. 취소 후 파일을 다시 선택해 주세요.":"PDF 확인 중 "+ready+" / "+entries.size());
            }
        };worker.execute();
    }
}
