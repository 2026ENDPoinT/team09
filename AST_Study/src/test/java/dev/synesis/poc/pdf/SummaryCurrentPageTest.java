package dev.synesis.poc.pdf;

import javax.swing.*;
import java.awt.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.Map;

/** Real summary rendering/scroll action, including title/outline pages without their own prose. */
public final class SummaryCurrentPageTest {
    static PdfWorkspace workspace;static JScrollPane scroll;static JPanel flow;
    public static void main(String[] args)throws Exception{
        SwingUtilities.invokeAndWait(()->{try{
            workspace=new PdfWorkspace(false,Files.createTempDirectory("summary-current-page-"));
            scroll=(JScrollPane)get("summaryScroll");flow=(JPanel)get("summaryFlow");
            String body="<!--OVERVIEWSTART--><p>강의 전체 흐름 <a href='page:2'>p.2</a></p><!--OVERVIEWEND-->"
                +"<!--READINGBREAK--><a name='synesis-summary-content'></a><h3>첫 학습 내용 <a href='page:3'>p.3</a></h3>"
                +("<p>본문 문장과 원문 설명을 충분히 길게 배치해요.</p>".repeat(22))
                +"<!--READINGBREAK--><a name='synesis-summary-content'></a><h3>다음 학습 내용 <a href='page:7'>p.7</a></h3>"
                +("<p>뒤쪽 학습 내용을 설명해요.</p>".repeat(22));
            Method render=PdfWorkspace.class.getDeclaredMethod("renderSummaryContent",String.class,Map.class);render.setAccessible(true);render.invoke(workspace,body,Map.of());layout();
            var first=SummaryPageNavigator.find(flow,3);var later=SummaryPageNavigator.find(flow,7);
            check(first!=null&&later!=null,"real rendered page targets missing");
            check(SummaryPageNavigator.find(flow,2)==null,"overview must not become the page target");
            check(SummaryPageNavigator.findNearest(flow,2).equals(first),"outline page must lead to the first real explanation");
            check(SummaryPageNavigator.findNearest(flow,5).equals(later),"gap must lead to next explained page");
            check(SummaryPageNavigator.findNearest(flow,8).equals(later),"trailing gap must lead to last explanation");
            set("page",7);jump();
        }catch(Exception e){throw new RuntimeException(e);}});
        SwingUtilities.invokeAndWait(()->check(scroll.getViewport().getViewPosition().y>350,"current page action did not scroll to exact page"));
        SwingUtilities.invokeAndWait(()->{try{set("page",2);jump();}catch(Exception e){throw new RuntimeException(e);}});
        SwingUtilities.invokeAndWait(()->{check(scroll.getViewport().getViewPosition().y<350,"current page action stayed at old position for outline page");workspace.close();});
        System.out.println("PASS SummaryCurrentPage: exact page, overview exclusion, gaps and actual scroll action");System.exit(0);
    }
    static Object get(String name)throws Exception{Field f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);return f.get(workspace);}
    static void set(String name,Object value)throws Exception{Field f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);f.set(workspace,value);}
    static void jump()throws Exception{Method m=PdfWorkspace.class.getDeclaredMethod("scrollSummaryToCurrentPage");m.setAccessible(true);m.invoke(workspace);}
    static void layout(){scroll.getViewport().setExtentSize(new Dimension(620,350));scroll.getViewport().setSize(620,350);flow.setSize(620,Math.max(1,flow.getPreferredSize().height));flow.doLayout();}
    static void check(boolean pass,String reason){if(!pass)throw new AssertionError(reason);}
}
