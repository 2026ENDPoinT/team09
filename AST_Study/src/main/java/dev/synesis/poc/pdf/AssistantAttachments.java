package dev.synesis.poc.pdf;

import javax.swing.*;
import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.datatransfer.*;
import java.awt.event.ActionEvent;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Decode, resize, persist and thumbnail once off the EDT; layout only uses tiny cached images. */
final class AssistantAttachments implements AutoCloseable {
    record Item(String path,ImageIcon thumbnail) {}
    final JPanel panel=new JPanel(new BorderLayout());
    private final JPanel row=new JPanel(new FlowLayout(FlowLayout.LEFT,6,0));
    private final List<Item> items=new ArrayList<>();
    private final ExecutorService io=Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"assistant-images");t.setDaemon(true);return t;});
    private final Path folder;
    private final Consumer<String> status;
    private final Runnable changed;
    private boolean closed;
    private int loading,generation;
    AssistantAttachments(Path folder,Consumer<String> status,Runnable changed){
        this.folder=folder;this.status=status;this.changed=changed;
        panel.setOpaque(false);row.setOpaque(false);panel.setVisible(false);
        JScrollPane scroll=new dev.synesis.poc.ui.UnifiedScrollPane(row);scroll.setOpaque(false);scroll.getViewport().setOpaque(false);scroll.setBorder(null);
        scroll.setVerticalScrollBarPolicy(JScrollPane.VERTICAL_SCROLLBAR_NEVER);scroll.setHorizontalScrollBarPolicy(JScrollPane.HORIZONTAL_SCROLLBAR_AS_NEEDED);
        scroll.getHorizontalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);panel.add(scroll);panel.setPreferredSize(new Dimension(220,84));
    }
    boolean loading(){return loading>0;}
    boolean empty(){return items.isEmpty();}
    List<Item> take(){List<Item> sent=List.copyOf(items);items.clear();refresh();return sent;}
    void clear(){generation++;items.clear();refresh();}
    void choose(Component parent){
        JFileChooser chooser=new JFileChooser();chooser.setDialogTitle("비서에게 보낼 이미지 선택");chooser.setMultiSelectionEnabled(true);
        chooser.setFileFilter(new javax.swing.filechooser.FileNameExtensionFilter("이미지 (PNG, JPG)","png","jpg","jpeg"));
        if(chooser.showOpenDialog(parent)==JFileChooser.APPROVE_OPTION)for(java.io.File f:chooser.getSelectedFiles())add(f.toPath());
    }
    void installPaste(JTextArea input){
        Action textPaste=input.getActionMap().get("paste-from-clipboard");
        Action paste=new AbstractAction(){public void actionPerformed(ActionEvent event){
            try{Transferable value=Toolkit.getDefaultToolkit().getSystemClipboard().getContents(null);
                if(value!=null&&value.isDataFlavorSupported(DataFlavor.javaFileListFlavor)){
                    @SuppressWarnings("unchecked") List<java.io.File> files=(List<java.io.File>)value.getTransferData(DataFlavor.javaFileListFlavor);
                    if(!files.isEmpty()){for(java.io.File f:files)add(f.toPath());return;}
                }
                if(value!=null&&value.isDataFlavorSupported(DataFlavor.imageFlavor)){Image image=(Image)value.getTransferData(DataFlavor.imageFlavor);enqueue(()->fromImage(image));return;}
            }catch(Exception error){status.accept("클립보드 이미지를 읽지 못했어요.");}
            if(textPaste!=null)textPaste.actionPerformed(event);
        }};
        input.getActionMap().put("assistant-image-paste",paste);
        input.getInputMap().put(KeyStroke.getKeyStroke(java.awt.event.KeyEvent.VK_V,(GraphicsEnvironment.isHeadless()?java.awt.event.InputEvent.CTRL_DOWN_MASK:Toolkit.getDefaultToolkit().getMenuShortcutKeyMaskEx())),"assistant-image-paste");
        // Also covers the native context menu's Paste action.
        input.getActionMap().put("paste-from-clipboard",paste);
    }
    private interface ImageWork{Item run()throws Exception;}
    void add(Path path){enqueue(()->{
        if(!Files.isRegularFile(path)||Files.size(path)>20_000_000)throw new IllegalArgumentException("이미지는 파일당 20MB까지 첨부할 수 있어요.");
        return persist(readImage(path));
    });}
    private void enqueue(ImageWork work){
        if(closed)return;
        if(items.size()+loading>=8){status.accept("이미지는 최대 8장 첨부할 수 있어요.");return;}
        int expected=generation;loading++;changed.run();status.accept("이미지를 준비하고 있어요…");
        io.execute(()->{Item item=null;String error=null;try{item=work.run();}catch(Exception failure){error=failure instanceof IllegalArgumentException?failure.getMessage():"이미지를 읽지 못했어요. PNG/JPG 파일을 확인해 주세요.";}
            Item result=item;String message=error;
            SwingUtilities.invokeLater(()->{loading--;if(closed)return;if(expected==generation&&result!=null)items.add(result);refresh();status.accept(message!=null?message:items.size()+"장 첨부 · 이미지는 전송 시 크레딧에 포함돼요");});
        });
    }
    private Item fromImage(Image image)throws Exception{
        int w=image.getWidth(null),h=image.getHeight(null);checkDimensions(w,h);
        BufferedImage buffer=new BufferedImage(w,h,BufferedImage.TYPE_INT_RGB);Graphics2D g=buffer.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,w,h);g.drawImage(image,0,0,null);g.dispose();
        try{return persist(buffer);}finally{buffer.flush();}
    }
    private Item persist(BufferedImage source)throws Exception{
        checkDimensions(source.getWidth(),source.getHeight());BufferedImage image=resize(source,1600,1600);
        Path directory=folder.resolve("requests/attachments");Files.createDirectories(directory);Path path=directory.resolve(UUID.randomUUID()+".png");
        if(!ImageIO.write(image,"png",path.toFile()))throw new IllegalArgumentException("이미지 저장을 완료하지 못했어요.");
        Item item=new Item("requests/attachments/"+path.getFileName(),new ImageIcon(resize(image,82,58)));image.flush();source.flush();return item;
    }
    static List<Item> restore(Path folder,List<String> paths){
        List<Item> result=new ArrayList<>();Path root=folder.resolve("requests/attachments").toAbsolutePath().normalize();
        for(String relative:paths.stream().limit(8).toList())try{
            Path path=folder.resolve(relative).toAbsolutePath().normalize();if(!path.startsWith(root)||!Files.isRegularFile(path)||Files.size(path)>20_000_000||!path.toRealPath().startsWith(root.toRealPath()))continue;
            BufferedImage image=readImage(path);result.add(new Item(relative,new ImageIcon(resize(image,82,58))));image.flush();
        }catch(Exception ignored){}return List.copyOf(result);
    }
    private static BufferedImage readImage(Path path)throws Exception{
        try(var stream=ImageIO.createImageInputStream(path.toFile())){
            Iterator<javax.imageio.ImageReader> readers=ImageIO.getImageReaders(stream);if(!readers.hasNext())throw new IllegalArgumentException("PNG/JPG 이미지를 선택해 주세요.");
            var reader=readers.next();try{reader.setInput(stream);checkDimensions(reader.getWidth(0),reader.getHeight(0));return reader.read(0);}finally{reader.dispose();}
        }
    }
    private static void checkDimensions(int w,int h){if(w<1||h<1||(long)w*h>30_000_000)throw new IllegalArgumentException("첨부 이미지는 3천만 화소까지 지원해요.");}
    private static BufferedImage resize(BufferedImage source,int maxW,int maxH){double ratio=Math.min(1,Math.min((double)maxW/source.getWidth(),(double)maxH/source.getHeight()));int w=Math.max(1,(int)Math.round(source.getWidth()*ratio)),h=Math.max(1,(int)Math.round(source.getHeight()*ratio));BufferedImage out=new BufferedImage(w,h,BufferedImage.TYPE_INT_RGB);Graphics2D g=out.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,w,h);g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);g.drawImage(source,0,0,w,h,null);g.dispose();return out;}
    private void refresh(){row.removeAll();for(Item item:List.copyOf(items)){
        JPanel tile=new JPanel(new BorderLayout(2,0));tile.setOpaque(false);JLabel preview=new JLabel(item.thumbnail());preview.getAccessibleContext().setAccessibleName("첨부 이미지");tile.add(preview);
        JButton remove=new JButton("×");remove.setMargin(new Insets(0,3,0,3));remove.setToolTipText("이미지 첨부 취소");remove.addActionListener(e->{items.remove(item);refresh();});tile.add(remove,BorderLayout.EAST);row.add(tile);
        }panel.setVisible(!items.isEmpty());row.revalidate();row.repaint();changed.run();}
    static JPanel bubble(List<Item> items){JPanel strip=new JPanel(new GridLayout(0,3,5,5));strip.setOpaque(false);for(Item item:items){JLabel preview=new JLabel(item.thumbnail());preview.getAccessibleContext().setAccessibleName("보낸 이미지");strip.add(preview);}strip.setBorder(BorderFactory.createEmptyBorder(0,0,8,0));return strip;}
    @Override public void close(){closed=true;generation++;io.shutdownNow();}
}
