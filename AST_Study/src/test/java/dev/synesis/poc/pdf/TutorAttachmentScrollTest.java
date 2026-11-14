package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.SmoothScrollPane;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;
import javax.swing.*;

/** Real user-bubble attachment hierarchy, without a PDF, model call, or visible window. */
public final class TutorAttachmentScrollTest {
    public static void main(String[] args)throws Exception {
        try {
            SwingUtilities.invokeAndWait(()->{
                try {verify(1);verify(12);}catch(Exception e){throw new RuntimeException(e);}
            });
            System.out.println("TutorAttachmentScrollTest passed: thumbnail/strip wheel forwarding, fractional and block scrolling, Shift horizontal scrolling, resize.");
        }catch(Throwable error){error.printStackTrace();System.exit(1);}
        System.exit(0);
    }
    private static void verify(int count)throws Exception {
        Class<?> previewType=Class.forName(PdfWorkspace.class.getName()+"$TutorPreview");
        Constructor<?> previewConstructor=previewType.getDeclaredConstructor(String.class,ImageIcon.class);
        previewConstructor.setAccessible(true);
        List<Object> previews=new ArrayList<>();
        for(int i=0;i<count;i++)previews.add(previewConstructor.newInstance("screenshot-"+i,
            new ImageIcon(new BufferedImage(20,20,BufferedImage.TYPE_INT_RGB))));
        Class<?> type=Class.forName(PdfWorkspace.class.getName()+"$RoundedTutorBubble");
        Constructor<?> constructor=type.getDeclaredConstructor(String.class,boolean.class,int.class,int.class,Consumer.class,List.class);
        constructor.setAccessible(true);
        JComponent bubble=(JComponent)constructor.newInstance("<p>첨부한 자료를 설명해줘</p>",true,260,14,(Consumer<String>)s->{},previews);
        JPanel messages=new JPanel(null);messages.setPreferredSize(new Dimension(300,1600));
        messages.add(bubble);bubble.setBounds(0,250,260,bubble.getPreferredSize().height);
        JScrollPane chat=new SmoothScrollPane(messages);chat.setSize(330,240);chat.doLayout();
        JFrame host=new JFrame();host.setContentPane(chat);host.addNotify();
        try {
        chat.getViewport().setViewSize(new Dimension(300,1600));bubble.doLayout();
        Field field=type.getDeclaredField("previewStrip");field.setAccessible(true);
        JScrollPane strip=(JScrollPane)field.get(bubble);layout(strip);
        Component thumbnail=((Container)strip.getViewport().getView()).getComponent(0);
        JScrollBar vertical=chat.getVerticalScrollBar();vertical.setValue(300);
        int before=vertical.getValue();wheel(thumbnail,0,.25,MouseWheelEvent.WHEEL_UNIT_SCROLL);
        check(vertical.getValue()>before,"thumbnail swallowed fractional vertical wheel, attachments="+count);
        before=vertical.getValue();wheel(strip,0,-1,MouseWheelEvent.WHEEL_UNIT_SCROLL);
        check(vertical.getValue()<before,"strip swallowed upward wheel");
        before=vertical.getValue();wheel(strip.getViewport(),0,1,MouseWheelEvent.WHEEL_BLOCK_SCROLL);
        check(vertical.getValue()>before,"viewport swallowed block wheel");
        JScrollBar horizontal=strip.getHorizontalScrollBar();horizontal.setValue(0);
        before=vertical.getValue();wheel(thumbnail,InputEvent.SHIFT_DOWN_MASK,1,MouseWheelEvent.WHEEL_UNIT_SCROLL);
        if(count>1) {
            check(horizontal.getValue()>0,"Shift wheel no longer scrolls attachment strip");
            check(vertical.getValue()==before,"Shift wheel also scrolled chat");
            horizontal.setValue(Integer.MAX_VALUE);before=vertical.getValue();
            wheel(thumbnail,0,1,MouseWheelEvent.WHEEL_UNIT_SCROLL);
            check(vertical.getValue()>before,"horizontal endpoint trapped vertical chat scroll");
        } else check(vertical.getValue()>before,"non-overflowing strip trapped Shift wheel");
        strip.setSize(180,84);layout(strip);vertical.setValue(300);before=vertical.getValue();
        wheel(thumbnail,0,1,MouseWheelEvent.WHEEL_UNIT_SCROLL);
        check(vertical.getValue()>before,"resized strip swallowed vertical wheel");
        }finally {host.dispose();}
    }
    private static void wheel(Component target,int modifiers,double rotation,int scrollType) {
        target.dispatchEvent(new MouseWheelEvent(target,MouseEvent.MOUSE_WHEEL,System.currentTimeMillis(),modifiers,
            5,5,5,5,0,false,scrollType,3,(int)Math.signum(rotation),rotation));
    }
    private static void layout(Container container) {
        container.doLayout();
        for(Component child:container.getComponents())if(child instanceof Container nested)layout(nested);
    }
    private static void check(boolean okay,String message){if(!okay)throw new AssertionError(message);}
}
