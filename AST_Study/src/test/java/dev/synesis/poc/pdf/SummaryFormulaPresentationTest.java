package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.event.MouseWheelEvent;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.text.View;

/** Offline contracts for semantic emphasis, grouping, legacy prose and native resize reuse. */
public final class SummaryFormulaPresentationTest {
    private static final Path OUT=Path.of("build/summary-formulas-20261017");
    private static final String WIDE=String.join("+",java.util.stream.IntStream.rangeClosed(1,40)
        .mapToObj(i->"p_{"+i+"}").toList())+"=0";
    private static final String MARKDOWN="""
        ## 운동량 보존

        두 보존식은 함께 사용해요.

        > **보존법칙**
        >
        > 운동량
        > $$
        > m_1v_{1i}+m_2v_{2i}=m_1v_{1f}+m_2v_{2f}
        > $$
        >
        > 에너지
        > $$E_i=E_f$$
        >
        > 외력이 없고 탄성 충돌일 때 적용해요.

        다음은 중간 계산이에요.
        \\[m_1(v_{1i}-v_{1f})=m_2(v_{2f}-v_{2i})\\]
        를 얻어요.

        같은 법칙의 다른 표현은 \\(p_i=p_f\\), 또는
        $$m_1v_{1i}+m_2v_{2i}=m_1v_{1f}+m_2v_{2f}$$
        가 성립해요.

        ```text
        > $$literal_code$$
        ```
        """;

    public static void main(String[] args)throws Exception {
        Files.createDirectories(OUT);
        try {SwingUtilities.invokeAndWait(()->{try {run();}catch(Exception e){throw new RuntimeException(e);}});}
        catch(Throwable failure) {failure.printStackTrace();System.exit(1);}
        System.out.println("SummaryFormulaPresentationTest passed");System.exit(0);
    }
    private static void run()throws Exception {
        String rendered=StudyMarkdown.renderWithScrollableMath(MARKDOWN,14);
        check(!rendered.contains("$$") || rendered.contains("literal_code"),"quoted multiline math failed");
        SummarySkin.FormulaPresentation prep=SummarySkin.prepare(rendered);
        check(prep.groups().size()==1,"related core formulas were not one group");
        String group=prep.groups().get("0").body();
        check(count(group,"<math ")==2 && !group.contains("&gt;"),"quote markers leaked into LaTeX");
        String plain=SummarySkin.document("",prep.body(),14);
        check(!plain.contains("<p>가 성립해요.</p>") && !plain.contains("<p>를 얻어요.</p>"),"legacy sentence tail detached");
        StudyHtmlPane prose=new StudyHtmlPane(true);prose.setReadingSkin(true);prose.setText(plain);
        prose.setSize(600,Short.MAX_VALUE);prose.modelToView2D(prose.getDocument().getLength());
        check(countViews(prose.getUI().getRootView(prose),"CardView")==0,"unmarked equations gained emphasis");
        String ordinaryQuote=StudyMarkdown.render("> 매출액 - 비용 = 당기순이익",14);
        check(SummarySkin.prepare(ordinaryQuote).groups().isEmpty(),"ordinary text quote became a formula group");
        String compare=StudyMarkdown.render("> $$\n> x>0\n> $$",14);
        check(compare.contains("aria-label='x&gt;0'"),"real greater-than operator was stripped");
        String nested=StudyMarkdown.render("> 바깥\n>\n> > $$x=1$$\n>\n> 마지막 조건",14);
        check(SummarySkin.prepare(nested).groups().get("0").body().contains("마지막 조건"),"nested quote was truncated");
        String legacyWide=StudyMarkdown.renderWithScrollableMath("이것은 \\("+WIDE+"\\)가 성립해요.",14);
        var legacy=SummarySkin.prepare(legacyWide);
        check(legacy.groups().size()==1 && !legacy.groups().get("0").emphasized(),"wide inline math gained emphasis");
        check(legacy.groups().get("0").body().contains("가 성립해요.") && !legacy.body().contains("가 성립해요."),
            "wide saved formula left its sentence tail in a separate pane");

        PdfWorkspace workspace=new PdfWorkspace(false,OUT.resolve("unused-library"));
        try {
            set(workspace,"summaryReadingSkin",true);
            ((JSlider)get(workspace,"summaryFontSize")).setValue(14);
            JScrollPane scroll=(JScrollPane)get(workspace,"summaryScroll");
            JPanel flow=(JPanel)get(workspace,"summaryFlow");
            Method render=PdfWorkspace.class.getDeclaredMethod("renderSummaryContent",String.class,Map.class);render.setAccessible(true);
            String wide=StudyMarkdown.renderWithScrollableMath("> **관련 식**\n>\n> $$x=1$$\n>\n> $$"+WIDE+"$$\n>\n> 적용 조건은 유지해요.",14);
            String body=rendered+"<!--READINGBREAK-->"+wide;
            render.invoke(workspace,body,Map.of());layout(scroll,flow,800);
            check(groups(flow).size()==2,"wide equation split its group");
            check(text(flow).contains("적용 조건은 유지해요.") && text(flow).contains("literal_code"),"labels/conditions/code lost");
            String before=text(flow);
            List<StudyHtmlPane> panes=panes(flow);long[] revisions=panes.stream().mapToLong(StudyHtmlPane::contentRevision).toArray();
            List<SummaryFormulaGroup> groups=groups(flow);
            for(int width:new int[]{800,646,340,240,800}) {
                layout(scroll,flow,width);
                check(text(flow).equals(before),"resize dropped or duplicated formula text");
                for(int i=0;i<panes.size();i++)check(panes.get(i).contentRevision()==revisions[i],"resize reparsed a document");
                for(StudyHtmlPane p:panes) {
                    if(p.getDocument().getText(0,p.getDocument().getLength()).isBlank())continue;
                    var end=p.modelToView2D(p.getDocument().getLength());
                    check(end==null || end.getMaxY()<=p.getHeight()+2,"formula group clipped its final line: width="+width
                        +", pane="+p.getSize()+", end="+end+", text="+p.getDocument().getText(0,Math.min(70,p.getDocument().getLength())));
                }
                snapshot(flow,width);
                StudyHtmlPane grouped=panes(groups(flow).get(0)).get(0);
                List<Rectangle> equations=new ArrayList<>();
                mathAllocations(grouped.getUI().getRootView(grouped),new Rectangle(0,0,grouped.getWidth(),grouped.getHeight()),equations);
                if(width>=646)for(Rectangle equation:equations)
                    check(Math.abs(equation.getCenterX()-grouped.getWidth()/2.0)<5,"formula center did not recover after resize");
            }
            render.invoke(workspace,body,Map.of());layout(scroll,flow,340);
            check(groups(flow).equals(groups),"unchanged group rebuilt");
            JScrollPane wideScroll=(JScrollPane)groups.get(1).getComponent(0);
            check(wideScroll.getHorizontalScrollBar().getMaximum()>wideScroll.getHorizontalScrollBar().getVisibleAmount(),"wide formula no scroll range");
            wideScroll.getHorizontalScrollBar().setValue(Integer.MAX_VALUE);
            check(wideScroll.getHorizontalScrollBar().getValue()>0,"wide formula end unreachable");
            wideScroll.getHorizontalScrollBar().setValue(0);
            scroll.setSize(360,350);scroll.doLayout();layout(scroll,flow,340);
            scroll.getVerticalScrollBar().setValues(0,350,0,flow.getHeight());
            wideScroll.dispatchEvent(new MouseWheelEvent(wideScroll,MouseWheelEvent.MOUSE_WHEEL,
                System.currentTimeMillis(),0,5,5,0,false,MouseWheelEvent.WHEEL_UNIT_SCROLL,3,1));
            check(wideScroll.getHorizontalScrollBar().getValue()==0,"vertical wheel scrolled equation sideways");
            check(scroll.getVerticalScrollBar().getValue()>0,"wheel did not reach outer summary");
            render.invoke(workspace,wide+"<!--READINGBREAK-->"+wide,Map.of());layout(scroll,flow,340);
            check(groups(flow).size()==2 && count(text(flow),"적용 조건은 유지해요.")==2,"repeated group lost from native reuse");
            set(workspace,"summaryReadingSkin",false);render.invoke(workspace,wide,Map.of());layout(scroll,flow,340);
            check(groups(flow).isEmpty() && ((Map<?,?>)get(workspace,"summaryFormulaGroups")).isEmpty(),"legacy fallback retained group cache");
            set(workspace,"summaryReadingSkin",true);
            render.invoke(workspace,"<!--OVERVIEWSTART-->"+wide+"<p><a href='page:1'>근거 p.1</a></p><!--OVERVIEWEND--><h3>학습 본문</h3>",Map.of());
            SummaryOverviewLoading completed=(SummaryOverviewLoading)get(workspace,"summaryOverviewLoading");
            JPanel overview=(JPanel)get(workspace,"summaryOverviewContent");
            for(int width:new int[]{800,340,240,800}) {
                layout(scroll,flow,width);
                check(completed.getParent()==flow && completed.completed(),"rich overview did not stay in its native card");
                check(groups(overview).size()==1 && groups(flow).isEmpty(),"overview formulas escaped their card");
                check(text(overview).contains("적용 조건은 유지해요.") && text(overview).contains("근거 p.1"),"overview conditions/citations lost");
                for(Component child:overview.getComponents())if(child instanceof StudyHtmlPane pane)check(!pane.isOpaque(),"overview prose covered the card background");
            }
            System.out.println("Fixture: 2 grouped core sets; unmarked derivations stay plain; native documents reused across resize.");
        } finally {workspace.close();}
    }
    private static int count(String s,String part){return s.split(java.util.regex.Pattern.quote(part),-1).length-1;}
    private static List<SummaryFormulaGroup> groups(Container c) {
        List<SummaryFormulaGroup> result=new ArrayList<>();
        for(Component child:c.getComponents())if(child instanceof SummaryFormulaGroup group)result.add(group);
        return result;
    }
    private static List<StudyHtmlPane> panes(Container c) {
        List<StudyHtmlPane> result=new ArrayList<>();
        for(Component child:c.getComponents())if(child instanceof StudyHtmlPane p)result.add(p);
            else if(child instanceof Container nested)result.addAll(panes(nested));
        return result;
    }
    private static String text(Container c)throws Exception {
        StringBuilder result=new StringBuilder();for(StudyHtmlPane pane:panes(c))
            result.append(pane.getDocument().getText(0,pane.getDocument().getLength()));
        return result.toString();
    }
    private static int countViews(View view,String name) {
        int count=view.getClass().getSimpleName().equals(name)?1:0;
        for(int i=0;i<view.getViewCount();i++)count+=countViews(view.getView(i),name);
        return count;
    }
    private static void mathAllocations(View view,Shape allocation,List<Rectangle> result) {
        if(view.getClass().getSimpleName().equals("MathView"))result.add(allocation.getBounds());
        for(int i=0;i<view.getViewCount();i++) {
            Shape child=view.getChildAllocation(i,allocation);
            if(child!=null)mathAllocations(view.getView(i),child,result);
        }
    }
    private static void layout(JScrollPane scroll,JPanel flow,int width) {
        scroll.getViewport().setExtentSize(new Dimension(width,700));scroll.getViewport().setSize(width,700);
        flow.setSize(width,Math.max(1,flow.getPreferredSize().height));flow.doLayout();nested(flow);
    }
    private static void nested(Container c){for(Component child:c.getComponents())
        if(child instanceof Container n && !(child instanceof JEditorPane)){n.doLayout();nested(n);}}
    private static void snapshot(JPanel flow,int width)throws Exception {
        BufferedImage b=new BufferedImage(width,Math.min(2400,flow.getHeight()),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=b.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,width,b.getHeight());flow.paint(g);g.dispose();
        ImageIO.write(b,"png",OUT.resolve("formulas-"+width+".png").toFile());
    }
    private static Object get(Object o,String name)throws Exception {Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    private static void set(Object o,String name,Object value)throws Exception {Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);f.set(o,value);}
    private static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
}
