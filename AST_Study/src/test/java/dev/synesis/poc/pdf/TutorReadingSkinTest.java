package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.*;
import javax.swing.*;
import javax.swing.text.View;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import java.util.function.Consumer;
import javax.imageio.ImageIO;

/** Offline tutor-only skin contracts, including the existing wheel/fade palette and cache. */
public final class TutorReadingSkinTest {
    public static void main(String[] args)throws Exception {
        Thread.setDefaultUncaughtExceptionHandler((t,e)->{e.printStackTrace();System.exit(1);});
        SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("TutorReadingSkinTest passed: grouped vector cards, tables/lists/source chips, tutor scroll palette/fades/wheel forwarding, resize/cache, streaming reuse and unchanged user skin.");System.exit(0);
    }
    private static void run()throws Exception {
        String wide=String.join("+",java.util.stream.IntStream.range(0,35).mapToObj(i->"p_{"+i+"}").toList())+"=0";
        String markdown="> **핵심 관계식**\n>\n> $$p=mv$$\n>\n> $$"+wide+"$$\n>\n> 외력이 없을 때 적용해요.\n\n"
            +"1. 계를 정해요.\n2. 외력을 확인해요.\n\n| 구분 | 의미 |\n|---|---|\n| 운동량 | 질량과 속도의 곱 |\n\n"
            +"```text\nliteral > code stays code\n```\n\n";
        String content=StudyMarkdown.renderWithScrollableMath(markdown,16)+"<p><a href='page:3'>p.3</a></p>";
        Class<?> type=Class.forName("dev.synesis.poc.pdf.PdfWorkspace$RoundedTutorBubble");
        Constructor<?> ctor=type.getDeclaredConstructor(String.class,boolean.class,int.class,int.class,Consumer.class,List.class);ctor.setAccessible(true);
        List<String> links=new ArrayList<>();JPanel bubble=(JPanel)ctor.newInstance(content,false,574,16,(Consumer<String>)links::add,List.of());
        Method resize=type.getDeclaredMethod("reflowWidth",int.class);resize.setAccessible(true);
        Method update=type.getDeclaredMethod("updateContent",String.class,int.class,int.class);update.setAccessible(true);
        List<SummaryFormulaGroup> groups=groups(bubble);require(groups.size()>=2,"formula/table native cards missing");
        List<StudyHtmlPane> panes=panes(bubble);long[] revisions=panes.stream().mapToLong(StudyHtmlPane::contentRevision).toArray();
        Path out=Files.createTempDirectory("synesis-tutor-reading-");
        for(int width:new int[]{574,300,820,300}) {
            resize.invoke(bubble,width);bubble.setSize(bubble.getPreferredSize());tree(bubble);
            require(groups(bubble).equals(groups)&&panes(bubble).equals(panes),"width-only resize replaced documents/cards");
            for(int i=0;i<panes.size();i++)require(panes.get(i).contentRevision()==revisions[i],"width-only resize parsed HTML");
            if(width==574||width==300)snapshot(bubble,out.resolve("tutor-"+width+".png"));
        }
        Map<String,Integer> views=new HashMap<>();for(StudyHtmlPane pane:panes)count(pane.getUI().getRootView(pane),views);
        require(views.getOrDefault("MathView",0)==2&&views.getOrDefault("NumberedListView",0)==1,"math/list views missing");
        require(views.getOrDefault("CitationView",0)>0&&panes.stream().anyMatch(p->p.getText().contains("study-table")),"table/source-chip skin missing");
        JScrollPane outer=new JScrollPane(bubble);outer.setWheelScrollingEnabled(false);int[] vertical={0};outer.addMouseWheelListener(e->vertical[0]++);
        for(SummaryFormulaGroup group:groups){
            JScrollPane scroll=(JScrollPane)group.getComponent(0);
            require(scroll instanceof FadeScrollPane,"tutor overflow edge fades removed");
            require(Boolean.TRUE.equals(scroll.getClientProperty("synesis.tutorScroll")),"tutor wheel mode not configured");
            Field thumb=FadingScrollBarUI.class.getDeclaredField("thumbColor");thumb.setAccessible(true);
            require(thumb.get(scroll.getHorizontalScrollBar().getUI()).equals(MistWorkspaceTheme.MUTED),"tutor scroll palette changed");
            Field opacity=FadingScrollBarUI.class.getDeclaredField("idleOpacity");opacity.setAccessible(true);
            require(Math.abs(opacity.getFloat(scroll.getHorizontalScrollBar().getUI())-.38f)<.001,"tutor scrollbar opacity changed");
            JScrollBar bar=scroll.getHorizontalScrollBar();scroll.getViewport().setExtentSize(new Dimension(100,100));scroll.getViewport().setViewSize(new Dimension(2000,100));bar.setValues(0,100,0,2000);bar.setVisible(true);
            scroll.dispatchEvent(wheel(scroll,true,.5));require(bar.getValue()==18,"tutor precise Shift-wheel distance changed: "+bar.getValue()+" max="+bar.getMaximum()+" extent="+bar.getVisibleAmount());
            int before=vertical[0];scroll.dispatchEvent(wheel(scroll,false,.5));require(vertical[0]==before+1,"vertical wheel did not reach chat");
        }
        SummaryFormulaGroup first=groups.getFirst();update.invoke(bubble,content+"<p>이어서 설명해요.</p>",300,16);
        require(groups(bubble).getFirst()==first,"streaming suffix rebuilt the completed formula card");
        JPanel user=(JPanel)ctor.newInstance(content,true,300,16,(Consumer<String>)s->{},List.of());
        require(groups(user).isEmpty(),"assistant card skin leaked into user message");
        for(StudyHtmlPane pane:panes(user))require(!pane.getText().contains("study-table"),"user table markup changed");
        javax.swing.event.HyperlinkEvent link=new javax.swing.event.HyperlinkEvent(first.textPane(),javax.swing.event.HyperlinkEvent.EventType.ACTIVATED,null,"page:3");
        for(var listener:first.textPane().getHyperlinkListeners())listener.hyperlinkUpdate(link);
        require(links.contains("page:3"),"native card lost PDF navigation");
        System.out.println("Offscreen previews: "+out);
    }
    private static MouseWheelEvent wheel(Component c,boolean shift,double precise){return new MouseWheelEvent(c,MouseEvent.MOUSE_WHEEL,0,shift?InputEvent.SHIFT_DOWN_MASK:0,10,10,10,10,0,false,MouseWheelEvent.WHEEL_UNIT_SCROLL,3,1,precise);}
    private static void tree(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested&&child.isVisible())tree(nested);}
    private static List<StudyHtmlPane> panes(Container c){List<StudyHtmlPane> out=new ArrayList<>();for(Component child:c.getComponents())if(child instanceof StudyHtmlPane pane)out.add(pane);else if(child instanceof Container nested)out.addAll(panes(nested));return out;}
    private static List<SummaryFormulaGroup> groups(Container c){List<SummaryFormulaGroup> out=new ArrayList<>();for(Component child:c.getComponents())if(child instanceof SummaryFormulaGroup group)out.add(group);else if(child instanceof Container nested)out.addAll(groups(nested));return out;}
    private static void count(View v,Map<String,Integer> out){out.merge(v.getClass().getSimpleName(),1,Integer::sum);for(int i=0;i<v.getViewCount();i++)count(v.getView(i),out);}
    private static void snapshot(JComponent c,Path p)throws Exception{BufferedImage i=new BufferedImage(c.getWidth(),c.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=i.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,i.getWidth(),i.getHeight());c.printAll(g);g.dispose();ImageIO.write(i,"png",p.toFile());}
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
}
