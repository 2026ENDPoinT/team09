package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.geom.Rectangle2D;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.List;
import java.util.function.Consumer;
import javax.imageio.ImageIO;
import javax.swing.*;

/** Real Swing/math layout, no window, microphone, model or user data. */
public final class TutorBubbleLayoutTest {
    private static String ANSWER = "고립계의 운동량 보존은 **계에 작용하는 알짜 외력이 0이면 계 전체 운동량이 일정하게 유지된다**는 법칙이에요. "
        + "즉, 물체들 사이에 충돌이나 상호작용이 있어도 전체 운동량의 크기와 방향은 변하지 않아요.\n\n"
        + "운동량은 \\(\\vec{p}=m\\vec{v}\\)이고, 여러 물체로 이루어진 계의 전체 운동량은 각 물체의 운동량을 벡터로 더한 값이에요. 두 물체라면\n\n"
        + "$$\\vec{p}_{1i}+\\vec{p}_{2i}=\\vec{p}_{1f}+\\vec{p}_{2f}$$\n\n"
        + "충돌 전후에 전체 운동량이 같다는 뜻이에요.\n\n"
        + "| 물체 | 질량 | 속도 |\n|---|---|---|\n| A | 2kg | 3m/s |\n| B | 1kg | 0m/s |\n\n"
        + "마지막 문장까지 빠짐없이 보여야 해요. 끝.";

    public static void main(String[] args) throws Exception {
        if(args.length>0)ANSWER=com.google.gson.JsonParser.parseString(Files.readString(Path.of(args[0]))).getAsJsonObject().get("answer").getAsString();
        SwingUtilities.invokeAndWait(()->{
            try { run(); } catch(Exception e) { throw new RuntimeException(e); }
        });
        System.out.println("TutorBubbleLayoutTest passed");
        System.exit(0);
    }
    private static void run() throws Exception {
        Class<?> type=Class.forName("dev.synesis.poc.pdf.PdfWorkspace$RoundedTutorBubble");
        Constructor<?> constructor=type.getDeclaredConstructor(String.class,boolean.class,int.class,int.class,Consumer.class,List.class);
        constructor.setAccessible(true);
        Method update=type.getDeclaredMethod("updateContent",String.class,int.class,int.class);
        Method animate=type.getDeclaredMethod("animateSize",long.class);
        update.setAccessible(true);animate.setAccessible(true);
        for(int font:new int[]{16,24,32})for(int width:new int[]{250,287,360,574,820}) {
            JPanel bubble=(JPanel)constructor.newInstance("<p>답변 작성 중…</p>",false,width,font,(Consumer<String>)s->{},List.of());
            JPanel column=new JPanel();column.setLayout(new BoxLayout(column,BoxLayout.Y_AXIS));
            JPanel row=new JPanel(new FlowLayout(FlowLayout.LEFT,0,0));row.add(bubble);column.add(row);
            column.setSize(width+40,400);
            String content="<p class='tutor-name'>AI멘토</p>"+StudyMarkdown.render(ANSWER,font,true)+"<p>이번 답변 비용: $0.001</p>";
            update.invoke(bubble,content,width,font);
            animate.invoke(bubble,System.nanoTime()+16_000_000L);
            bubble.setSize(bubble.getPreferredSize());bubble.doLayout();
            assertFits(bubble,"growing document "+width+"/"+font);
            settle(bubble,animate);
            assertFits(bubble,"long "+width+"/"+font);
            // Narrowing causes real line wrapping and taller equations/paragraphs.
            update.invoke(bubble,content,250,font);
            settle(bubble,animate);
            assertFits(bubble,"narrow "+width+"/"+font);
            int tall=bubble.getPreferredSize().height;
            update.invoke(bubble,"<p>짧은 답변이에요.</p>",250,font);
            animate.invoke(bubble,System.nanoTime()+16_000_000L);
            int shrinking=bubble.getPreferredSize().height;
            if(shrinking>=tall || shrinking<=font*2+20)throw new AssertionError("Missing gradual shrink");
            settle(bubble,animate);
            assertFits(bubble,"short "+font);
        }
    }
    private static void settle(JPanel bubble,Method animate) throws Exception {
        long now=System.nanoTime();
        for(int i=1;i<=200;i++) {
            animate.invoke(bubble,now+i*16_000_000L);
            JPanel row=(JPanel)bubble.getParent();
            row.setMaximumSize(new Dimension(Integer.MAX_VALUE,bubble.getPreferredSize().height));
            Container column=row.getParent();
            column.setSize(column.getWidth(),column.getPreferredSize().height);
            column.doLayout();row.doLayout();bubble.doLayout();
        }
    }
    private static void assertFits(JPanel bubble,String label) throws Exception {
        Field primary=bubble.getClass().getDeclaredField("text");primary.setAccessible(true);
        JEditorPane text=(JEditorPane)primary.get(bubble);
        BufferedImage image=new BufferedImage(bubble.getWidth(),bubble.getHeight(),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,image.getWidth(),image.getHeight());bubble.printAll(g);g.dispose();
        Rectangle2D end=text.modelToView2D(text.getDocument().getLength());
        float natural=text.getUI().getRootView(text).getPreferredSpan(javax.swing.text.View.Y_AXIS);
        Path directory=Path.of("build/tutor-bubble-check");Files.createDirectories(directory);
        if(label.equals("long 574/24"))ImageIO.write(image,"png",directory.resolve("bubble.png").toFile());
        if(end==null || end.getMaxY()>text.getHeight()+1 || natural>text.getHeight()+1)
            throw new AssertionError(label+" clipped: text height="+text.getHeight()+", natural="+natural+", last="+end);
    }
}
