package dev.synesis.poc.pdf;

import javax.swing.*;
import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

/** Clipboard-independent attachment IO/limits and real user-bubble layout in a temp folder. */
public final class AssistantAttachmentTest {
    static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception{
        Path dir=Files.createTempDirectory("assistant-attachments-");System.setProperty("synesis.dataRoot",dir.resolve("data").toString());
        Path source=dir.resolve("screen.png");BufferedImage screenshot=new BufferedImage(2000,1000,BufferedImage.TYPE_INT_RGB);Graphics2D g=screenshot.createGraphics();g.setColor(Color.BLUE);g.fillRect(0,0,2000,1000);g.dispose();ImageIO.write(screenshot,"png",source.toFile());screenshot.flush();
        AtomicReference<AssistantAttachments> ref=new AtomicReference<>();AtomicReference<String> message=new AtomicReference<>();AtomicReference<List<AssistantAttachments.Item>> taken=new AtomicReference<>();
        SwingUtilities.invokeAndWait(()->{AssistantAttachments attachments=new AssistantAttachments(dir.resolve("assistant"),message::set,()->{});ref.set(attachments);for(int i=0;i<9;i++)attachments.add(source);check(message.get().contains("8장"),"ninth image not rejected");});
        long deadline=System.nanoTime()+10_000_000_000L;boolean[] loading={true};
        do{Thread.sleep(20);SwingUtilities.invokeAndWait(()->loading[0]=ref.get().loading());}while(loading[0]&&System.nanoTime()<deadline);
        check(!loading[0],"image worker stalled");
        SwingUtilities.invokeAndWait(()->{check(ref.get().panel.isVisible(),"preview hidden");taken.set(ref.get().take());check(!ref.get().panel.isVisible(),"composer did not shrink after send");ref.get().close();});
        List<AssistantAttachments.Item> images=taken.get();check(images.size()==8,"attachment count");
        for(var item:images){check(item.thumbnail().getIconWidth()<=82&&item.thumbnail().getIconHeight()<=58,"oversize thumbnail");BufferedImage image=ImageIO.read(dir.resolve("assistant").resolve(item.path()).toFile());check(image.getWidth()==1600&&image.getHeight()==800,"image payload not bounded");image.flush();}
        List<String> paths=new ArrayList<>(images.stream().map(AssistantAttachments.Item::path).toList());paths.add("../screen.png");
        check(AssistantAttachments.restore(dir.resolve("assistant"),List.of("../screen.png")).isEmpty(),"history can escape private attachment folder");
        check(AssistantAttachments.restore(dir.resolve("assistant"),paths).size()==8,"image history restore");
        SwingUtilities.invokeAndWait(()->{
            HomeAssistant view=new HomeAssistant();try{
                view.setSize(1120,800);view.doLayout();
                var method=HomeAssistant.class.getDeclaredMethod("addBubble",String.class,boolean.class,List.class);method.setAccessible(true);
                JPanel bubble=(JPanel)method.invoke(view,"이 코드가 왜 틀렸는지 설명해줘. 문장이 여러 줄로 바뀌어도 이미지가 겹치면 안 돼요.",true,images);
                var scrollField=HomeAssistant.class.getDeclaredField("scroll");scrollField.setAccessible(true);JScrollPane scroll=(JScrollPane)scrollField.get(view);scroll.getViewport().setSize(400,250);
                int wide=bubble.getPreferredSize().height;view.setSize(300,600);view.doLayout();
                // The real viewport follows the chat card on validation; emulate that offscreen.
                scroll.getViewport().setSize(210,250);
                int narrow=bubble.getPreferredSize().height;check(narrow>wide,"narrow image grid/text did not wrap");
                for(int i=0;i<200;i++){bubble.setSize(bubble.getPreferredSize());bubble.doLayout();}
                check(images.get(0).thumbnail()==taken.get().get(0).thumbnail(),"layout replaced cached thumbnail");
            }catch(Exception e){throw new RuntimeException(e);}finally{view.close();}
        });
        try(var pathsToDelete=Files.walk(dir)){for(Path path:pathsToDelete.sorted(Comparator.reverseOrder()).toList())Files.delete(path);}
        System.out.println("AssistantAttachmentTest OK · 8 images, worker IO, bounded payloads, safe restore, cached responsive bubble layout");
    }
}
