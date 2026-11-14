package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.*;
import java.util.function.Consumer;
import javax.swing.*;
import javax.swing.text.*;
import javax.swing.text.html.*;

/** Offline source-preserving selection, split-pane gestures and actual tutor request handoff. */
public final class StudySelectionActionsTest {
    private static JScrollPane boxedScroll,formulaScroll;
    private static StudySelectionActions boxedActions;
    private static Point stableScroll,stableFormulaScroll;
    public static void main(String[] args)throws Exception {
        try {
            SwingUtilities.invokeAndWait(()->{
                try {sourceMath();gestures();boxedGestures();highlightFrames();workspaceWiring();workspaceContext();}catch(Exception e){throw new RuntimeException(e);}
            });
            SwingUtilities.invokeAndWait(()->{
                check(boxedScroll.getViewport().getViewPosition().equals(stableScroll),"queued caret scrolling moved the outer document");
                check(formulaScroll.getViewport().getViewPosition().equals(stableFormulaScroll),"queued caret scrolling moved formula viewport");
                boxedActions.close();
            });
            System.out.println("StudySelectionActionsTest passed: continuous drag highlighting; fresh gestures and stable viewports; hidden summary/concept context with source math; unchanged user question and no API execution.");
        }catch(Throwable error){error.printStackTrace();System.exit(1);}
        System.exit(0);
    }
    private static void sourceMath()throws Exception {
        StudyHtmlPane pane=pane("앞 문장 $\\frac{a}{b}=c$ 뒤 문장\n\n$$\\begin{aligned}x&=y+1\\\\z&=2x\\end{aligned}$$");
        List<Element> maths=maths(pane);check(maths.size()==2,"source metadata lost in HTML document");
        Element inline=maths.get(0),display=maths.get(1);
        String part=pane.selectionMarkdown(inline.getStartOffset()+1,inline.getStartOffset()+2);
        check(part.equals("$\\frac{a}{b}=c$"),"partial formula was copied as a broken label: "+part);
        String all=pane.selectionMarkdown(0,pane.getDocument().getLength());
        check(all.contains("앞 문장")&&all.contains("뒤 문장")&&all.contains("$$\n\\begin{aligned}"),"mixed prose/display export failed");
        check(pane.selectionMarkdown(display.getStartOffset(),display.getEndOffset()).contains("z&=2x"),"related formula rows lost");
        Field cache=StudyHtmlPane.class.getDeclaredField("MATH_CACHE");cache.setAccessible(true);
        ((Map<?,?>)cache.get(null)).clear();
        check(pane.selectionMarkdown(inline.getStartOffset()+1,inline.getStartOffset()+2).equals(part),"source depended on icon cache");
        pane.setText("<html><body><math aria-label='\\noSuchFormulaCommand{x}' data-plain='fallback' display='block'>fallback</math></body></html>");
        check(pane.selectionMarkdown(0,pane.getDocument().getLength()).contains("\\noSuchFormulaCommand{x}"),"failed rendering discarded source math");
        pane.setText("<html><body><math aria-label='x &gt; y &amp; z' data-plain='relation'>relation</math></body></html>");
        check(pane.selectionMarkdown(0,pane.getDocument().getLength()).contains("x > y & z"),"math entities did not round-trip");
    }
    private static void gestures()throws Exception {
        JPanel root=new JPanel(null);root.setSize(650,600);
        StudyHtmlPane first=pane("첫 문장을 읽어요."),equation=pane("$$E=mc^2$$"),last=pane("마지막 설명이에요.");
        StudyHtmlPane[] panes={first,equation,last};
        for(int i=0;i<panes.length;i++){root.add(panes[i]);panes[i].setBounds(0,i*150,600,140);layout(panes[i]);}
        List<String> asked=new ArrayList<>();
        StudySelectionActions actions=new StudySelectionActions(root,asked::add,()->true,s->{});
        actions.refresh();actions.refresh();
        int listenerCount=first.getMouseMotionListeners().length;actions.refresh();
        check(first.getMouseMotionListeners().length==listenerCount,"rerender duplicated selection listeners");
        String text=plain(first);int start=text.indexOf("첫");int end=plain(last).indexOf("설명")+2;
        Point from=position(first,start),to=SwingUtilities.convertPoint(last,position(last,end),first);
        mouse(first,MouseEvent.MOUSE_PRESSED,from,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.BUTTON1);
        mouse(first,MouseEvent.MOUSE_DRAGGED,to,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.NOBUTTON);
        mouse(first,MouseEvent.MOUSE_RELEASED,to,0,MouseEvent.BUTTON1);
        String forward=actions.selectedMarkdown();
        check(forward.contains("첫 문장")&&forward.contains("$$\nE=mc^2\n$$")&&forward.contains("마지막 설명"),"cross-pane drag lost content: "+forward);
        mouse(equation,MouseEvent.MOUSE_DRAGGED,position(equation,2),InputEvent.BUTTON1_DOWN_MASK,MouseEvent.NOBUTTON);
        check(actions.selectedMarkdown().equals(forward),"a released gesture reused its previous anchor");
        mouse(first,MouseEvent.MOUSE_DRAGGED,position(first,3),InputEvent.BUTTON1_DOWN_MASK,MouseEvent.NOBUTTON);
        check(actions.selectedMarkdown().equals(forward),"native caret extended a completed gesture");
        JPopupMenu menu=actions.menu(forward);
        check(menu.getComponentCount()==2&&((JMenuItem)menu.getComponent(0)).getText().equals("AI멘토에게 이 부분 질문하기")
            &&((JMenuItem)menu.getComponent(1)).getText().equals("복사"),"selection menu actions missing");
        ((JMenuItem)menu.getComponent(0)).doClick();check(asked.equals(List.of(forward)),"menu changed selected source");
        for(int i=0;i<6;i++) {
            StudyHtmlPane current=i%2==0?first:last;
            int fresh=plain(current).indexOf(i%2==0?"읽":"설명");
            Point press=position(current,fresh),release=position(current,fresh+2);
            mouse(current,MouseEvent.MOUSE_PRESSED,press,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.BUTTON1);
            check(actions.selectedMarkdown().isEmpty(),"new press retained previous selection");
            mouse(current,MouseEvent.MOUSE_DRAGGED,release,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.NOBUTTON);
            mouse(current,MouseEvent.MOUSE_RELEASED,release,0,MouseEvent.BUTTON1);
            check(actions.selectedMarkdown().equals(i%2==0?"읽어":"설명"),"repeated drag reused previous anchor: "+actions.selectedMarkdown());
        }
        Point newStart=position(first,start),newEnd=position(first,start+2);
        MouseEvent popupDismissPress=new MouseEvent(first,MouseEvent.MOUSE_PRESSED,System.currentTimeMillis(),
            InputEvent.BUTTON1_DOWN_MASK,newStart.x,newStart.y,0,0,1,false,MouseEvent.BUTTON1);
        popupDismissPress.consume();first.dispatchEvent(popupDismissPress);
        check(actions.selectedMarkdown().isEmpty(),"popup-dismiss press retained old selection");
        mouse(first,MouseEvent.MOUSE_DRAGGED,newEnd,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.NOBUTTON);
        mouse(first,MouseEvent.MOUSE_RELEASED,newEnd,0,MouseEvent.BUTTON1);
        check(actions.selectedMarkdown().equals("첫"),"popup-dismiss drag reused native caret anchor: "+actions.selectedMarkdown());
        actions.close();
        actions=new StudySelectionActions(root,asked::add,()->false,s->{});actions.refresh();
        check(!((JMenuItem)actions.menu(forward).getComponent(0)).isEnabled(),"busy/unready tutor menu remained enabled");
        actions.close();
        // Use a fresh controller/root to test the reverse gesture without accumulating listeners.
        JPanel backward=new JPanel(null);backward.setSize(650,600);
        for(int i=0;i<panes.length;i++){backward.add(panes[i]);panes[i].putClientProperty(StudySelectionActions.class,null);}
        // The original controller is detached; invoke the fresh gesture listener only.
        StudySelectionActions reverse=new StudySelectionActions(backward,asked::add,()->true,s->{});reverse.refresh();
        int reverseStart=plain(last).indexOf("설명")+2;
        Point backFrom=position(last,reverseStart),backTo=SwingUtilities.convertPoint(first,position(first,start),last);
        mouse(last,MouseEvent.MOUSE_PRESSED,backFrom,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.BUTTON1);
        mouse(last,MouseEvent.MOUSE_DRAGGED,backTo,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.NOBUTTON);
        check(reverse.selectedMarkdown().equals(forward),"backward drag reversed or lost selected content");
        reverse.close();
    }
    private static void boxedGestures()throws Exception {
        JPanel root=new JPanel(null);root.setPreferredSize(new Dimension(650,1400));root.setSize(650,1400);
        StudyHtmlPane before=pane("이전 본문을 읽어요."),after=pane("다음 본문을 읽어요.");
        before.setBounds(24,120,600,120);root.add(before);layout(before);
        String tex="a="+"x_1+x_2+x_3+".repeat(12)+"x_4";
        SummaryFormulaGroup box=new SummaryFormulaGroup(new SummarySkin.FormulaGroup(StudyMarkdown.render("$$"+tex+"$$",16),true),16,s->{});
        box.setSize(500,1);int height=box.getPreferredSize().height;box.setBounds(24,260,500,height);root.add(box);layoutTree(box);
        after.setBounds(24,260+height+20,600,120);root.add(after);layout(after);
        boxedScroll=new dev.synesis.poc.ui.SmoothScrollPane(root);boxedScroll.setSize(650,420);boxedScroll.doLayout();
        boxedScroll.getViewport().setViewSize(new Dimension(650,1400));boxedScroll.getViewport().setViewPosition(new Point(0,100));
        boxedActions=new StudySelectionActions(root,s->{},()->true,s->{});boxedActions.refresh();
        StudyHtmlPane math=(StudyHtmlPane)get(box,"text");formulaScroll=(JScrollPane)get(box,"scroll");
        formulaScroll.getViewport().setViewPosition(new Point(40,0));
        stableScroll=boxedScroll.getViewport().getViewPosition();stableFormulaScroll=formulaScroll.getViewport().getViewPosition();
        // A measured formula pane can be much larger than its clipped viewport.
        // It must not intercept a drag whose pointer has reached the next paragraph.
        math.setSize(math.getWidth(),Short.MAX_VALUE);
        int mathStart=maths(math).get(0).getStartOffset()+1;
        Point from=position(math,mathStart),inside=position(math,mathStart+4);
        mouse(math,MouseEvent.MOUSE_PRESSED,from,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.BUTTON1);
        mouse(math,MouseEvent.MOUSE_DRAGGED,inside,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.NOBUTTON);
        mouse(math,MouseEvent.MOUSE_RELEASED,inside,0,MouseEvent.BUTTON1);
        check(boxedActions.selectedMarkdown().equals("$$\n"+tex+"\n$$"),"drag inside formula escaped into surrounding prose");
        Point outside=SwingUtilities.convertPoint(after,position(after,plain(after).indexOf("읽")),math);
        mouse(math,MouseEvent.MOUSE_PRESSED,from,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.BUTTON1);
        check(boxedActions.selectedMarkdown().isEmpty(),"formula press did not reset previous selection");
        mouse(math,MouseEvent.MOUSE_DRAGGED,outside,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.NOBUTTON);
        mouse(math,MouseEvent.MOUSE_RELEASED,outside,0,MouseEvent.BUTTON1);
        check(boxedActions.selectedMarkdown().contains(tex)&&boxedActions.selectedMarkdown().contains("다음 본문")
            &&!boxedActions.selectedMarkdown().contains("이전 본문"),"formula-to-prose drag was trapped or jumped");
        Point padding=new Point(8,8),end=SwingUtilities.convertPoint(after,position(after,plain(after).indexOf("읽")),box);
        mouse(box,MouseEvent.MOUSE_PRESSED,padding,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.BUTTON1);
        check(boxedActions.selectedMarkdown().isEmpty(),"formula padding press kept old selection");
        mouse(box,MouseEvent.MOUSE_DRAGGED,end,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.NOBUTTON);
        mouse(box,MouseEvent.MOUSE_RELEASED,end,0,MouseEvent.BUTTON1);
        check(boxedActions.selectedMarkdown().contains(tex)&&boxedActions.selectedMarkdown().contains("다음 본문"),"formula padding could not start continuous selection");
        int begin=plain(before).indexOf("본문"),finish=plain(after).indexOf("읽");
        Point beginPoint=position(before,begin),finishPoint=position(after,finish);
        Point forwardEnd=SwingUtilities.convertPoint(after,finishPoint,before);
        mouse(before,MouseEvent.MOUSE_PRESSED,beginPoint,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.BUTTON1);
        for(int step=1;step<=30;step++) {
            Point during=new Point(beginPoint.x+(forwardEnd.x-beginPoint.x)*step/30,
                beginPoint.y+(forwardEnd.y-beginPoint.y)*step/30);
            mouse(before,MouseEvent.MOUSE_DRAGGED,during,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.NOBUTTON);
            for(StudyHtmlPane pane:List.of(before,math,after))if(pane.getSelectionStart()!=pane.getSelectionEnd()) {
                ((DefaultCaret)pane.getCaret()).focusLost(new FocusEvent(pane,FocusEvent.FOCUS_LOST,false,null,FocusEvent.Cause.MOUSE_EVENT));
                check(pane.getCaret().isSelectionVisible(),"mixed prose/formula highlight vanished before release");
                check(java.util.Arrays.stream(pane.getHighlighter().getHighlights()).anyMatch(h->h.getStartOffset()==pane.getSelectionStart()&&h.getEndOffset()==pane.getSelectionEnd()),
                    "mixed drag highlight did not match live range");
            }
        }
        mouse(before,MouseEvent.MOUSE_RELEASED,forwardEnd,0,MouseEvent.BUTTON1);
        String continuous=boxedActions.selectedMarkdown();
        check(continuous.contains("본문을 읽어요.")&&continuous.contains(tex)&&continuous.contains("다음 본문"),"body/formula/body selection was not continuous");
        Point reverseEnd=SwingUtilities.convertPoint(before,beginPoint,after);
        mouse(after,MouseEvent.MOUSE_PRESSED,finishPoint,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.BUTTON1);
        mouse(after,MouseEvent.MOUSE_DRAGGED,reverseEnd,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.NOBUTTON);
        mouse(after,MouseEvent.MOUSE_RELEASED,reverseEnd,0,MouseEvent.BUTTON1);
        check(boxedActions.selectedMarkdown().equals(continuous),"reverse selection changed the continuous content");
        check(boxedScroll.getViewport().getViewPosition().equals(stableScroll),"selection moved outer viewport before flush");
        check(formulaScroll.getViewport().getViewPosition().equals(stableFormulaScroll),"selection moved formula viewport before flush");
    }
    private static void layoutTree(Container container){container.doLayout();for(Component c:container.getComponents())if(c instanceof Container nested)layoutTree(nested);}
    private static void highlightFrames()throws Exception {
        StudyHtmlPane pane=pane("선택 표시가 드래그 중에도 안정적으로 유지되어야 해요.");pane.setSize(600,140);layout(pane);
        JPanel root=new JPanel(null);root.setSize(650,200);root.add(pane);
        StudySelectionActions actions=new StudySelectionActions(root,s->{},()->true,s->{});actions.refresh();
        int start=plain(pane).indexOf("선택");pane.setStudySelection(start,start+2);
        Highlighter.Highlight stable=pane.getHighlighter().getHighlights()[0];
        for(int i=start+3;i<plain(pane).length()-1;i++) {
            pane.setStudySelection(start,i);
            check(pane.getHighlighter().getHighlights().length==1&&pane.getHighlighter().getHighlights()[0]==stable,
                "drag collapsed and recreated its highlight");
            ((DefaultCaret)pane.getCaret()).focusLost(new FocusEvent(pane,FocusEvent.FOCUS_LOST,false,null,FocusEvent.Cause.MOUSE_EVENT));
            check(pane.getCaret().isSelectionVisible()&&pane.getHighlighter().getHighlights().length==1,"focus change hid active drag highlight");
            layout(pane);
        }
        pane.setStudySelection(start,start);check(pane.getHighlighter().getHighlights().length==0,"fresh click retained highlight");
        actions.close();
    }
    @SuppressWarnings("unchecked")
    private static void workspaceContext()throws Exception {
        PdfWorkspace workspace=new PdfWorkspace(false,Files.createTempDirectory("synesis-selection-context-"));
        ((ExecutorService)get(workspace,"tutorJobs")).shutdownNow();HoldingExecutor held=new HoldingExecutor();set(workspace,"tutorJobs",held);
        try {
            String sentence="질량이 일정할 때 이 관계는 운동량의 시간 변화율을 뜻해요.";
            String formula="\\frac{d\\vec{p}}{dt}=\\sum_i\\vec{F}_i";
            JsonObject block=new JsonObject();block.addProperty("title","고립계의 운동량 보존");
            block.addProperty("body","앞의 관계식이에요.\n\n> $$"+formula+"$$\n\n"+sentence+"\n\n이어지는 설명이에요.");
            block.add("evidence",JsonParser.parseString("[{\"page\":2,\"quote\":\"운동량 보존\"}]").getAsJsonArray());
            Method renderBlock=PdfWorkspace.class.getDeclaredMethod("summaryBlock",JsonObject.class,String.class,boolean.class,Map.class);renderBlock.setAccessible(true);
            String body=(String)renderBlock.invoke(workspace,block,"document/0/section-1",true,new java.util.LinkedHashMap<String,SlideLens.Request>());
            call(workspace,"renderSummaryContent",new Class<?>[]{String.class,Map.class},body,Map.of());
            JScrollPane summaryScroll=(JScrollPane)get(workspace,"summaryScroll");layoutStudyScroll(summaryScroll);
            List<StudyHtmlPane> panes=new ArrayList<>();collect((Container)get(workspace,"summaryFlow"),panes);
            StudyHtmlPane selected=null;
            for(StudyHtmlPane pane:panes)if(plain(pane).contains(sentence)){selected=pane;break;}
            check(selected!=null,"summary sentence missing");int offset=plain(selected).indexOf(sentence);selected.setStudySelection(offset,offset+sentence.length());
            StudySelectionActions actions=(StudySelectionActions)get(workspace,"summarySelection");
            JsonObject context=actions.selectionContext(sentence);
            check(context.get("title").getAsString().equals(block.get("title").getAsString()),"summary title not resolved from local origin");
            check(context.getAsJsonArray("pages").get(0).getAsInt()==2,"selected PDF page missing");
            check(context.get("context").getAsString().contains(formula),"preceding native formula missing from hidden context: "+context);
            check(context.get("context").getAsString().length()<=StudySelectionContext.MAX_CONTEXT,"context grew beyond bound");
            JPopupMenu frozen=actions.menu(sentence);
            JsonObject index=JsonParser.parseString("{\"pages\":[{},{}]}").getAsJsonObject();set(workspace,"index",index);
            JsonObject generated=JsonParser.parseString("{\"kind\":\"ai_generated\",\"scope\":\"document\",\"page\":0,\"overview\":{},\"sections\":[],\"concepts\":[{\"name\":\"고립계\",\"pages\":[2],\"entries\":[]}]}").getAsJsonObject();
            JsonObject concept=generated.getAsJsonArray("concepts").get(0).getAsJsonObject();
            JsonObject entry=new JsonObject();entry.addProperty("definition","$$"+formula+"$$");entry.addProperty("explanation",sentence);
            entry.add("evidence",block.get("evidence").deepCopy());concept.getAsJsonArray("entries").add(entry);set(workspace,"generated",generated);
            call(workspace,"showConcepts");expandConcept((Container)get(workspace,"conceptList"),"고립계");layoutStudyScroll((JScrollPane)get(workspace,"conceptScroll"));
            panes.clear();collect((Container)get(workspace,"conceptList"),panes);
            for(StudyHtmlPane pane:panes)if(plain(pane).contains(sentence)){int start=plain(pane).indexOf(sentence);pane.setStudySelection(start,start+sentence.length());}
            JsonObject conceptContext=((StudySelectionActions)get(workspace,"conceptSelection")).selectionContext(sentence);
            check(conceptContext.get("origin").getAsString().equals("개념")&&conceptContext.get("title").getAsString().equals("고립계"),"concept origin/title missing");
            check(conceptContext.get("context").getAsString().contains(formula),"definition formula missing from concept explanation context");
            set(workspace,"tutorSideOpener",(Runnable)()->{});
            ((JMenuItem)frozen.getComponent(0)).setEnabled(true);((JMenuItem)frozen.getComponent(0)).doClick();
            check(held.commands.size()==1,"context added a model request");
            JsonObject request=null;
            for(Field field:held.commands.get(0).getClass().getDeclaredFields())if(field.getType()==JsonObject.class){field.setAccessible(true);request=(JsonObject)field.get(held.commands.get(0));}
            check(request!=null&&request.get("question").getAsString().equals("["+sentence+"]\n\n이 부분에 대해 상세히 설명해줘."),"hidden context altered visible question");
            check(request.getAsJsonObject("selectionContext").equals(context),"menu did not freeze the selected summary context");
            Object turn=((List<?>)get(workspace,"conversation")).get(0);
            check(get(turn,"question").equals(request.get("question").getAsString()),"hidden context leaked into user message");
            String huge="$$"+"x".repeat(1000)+"$$";
            check(!StudySelectionContext.bounded("앞 설명 "+huge+" 뒤 설명",480).contains("$"),"context truncated a formula instead of omitting it");
        }finally {workspace.close();}
    }
    private static void layoutStudyScroll(JScrollPane scroll) {
        scroll.setSize(650,420);scroll.doLayout();Container root=(Container)scroll.getViewport().getView();
        root.setSize(scroll.getViewport().getWidth(),Math.max(1,root.getPreferredSize().height));layoutTree(root);
        scroll.getViewport().setViewSize(root.getSize());scroll.doLayout();layoutTree(root);
    }
    @SuppressWarnings("unchecked")
    private static void workspaceWiring()throws Exception {
        Path library=Files.createTempDirectory("synesis-selection-");
        PdfWorkspace workspace=new PdfWorkspace(false,library);
        ExecutorService original=(ExecutorService)get(workspace,"tutorJobs");original.shutdownNow();
        HoldingExecutor held=new HoldingExecutor();set(workspace,"tutorJobs",held);
        try {
            set(workspace,"index",JsonParser.parseString("{\"pages\":[{\"number\":1}]}").getAsJsonObject());
            JsonObject generated=JsonParser.parseString("{\"kind\":\"ai_generated\",\"scope\":\"document\",\"page\":0,\"overview\":{\"body\":\"요약 내용\"},\"sections\":[],\"concepts\":[{\"name\":\"운동량\",\"definition\":\"정의 $p=mv$\",\"explanation\":\"설명 $F=ma$\",\"evidence\":[],\"easyExplanation\":\"쉽게 설명해요.\"}]}").getAsJsonObject();
            JsonObject concept=generated.getAsJsonArray("concepts").get(0).getAsJsonObject();
            JsonArray entries=new JsonArray();entries.add(concept.deepCopy());
            concept.add("entries",entries);concept.add("pages",new JsonArray());
            set(workspace,"generated",generated);
            call(workspace,"renderSummaryContent",new Class<?>[]{String.class,Map.class},"<p>요약 $x$</p>",Map.of());
            check(((JComponent)get(workspace,"summary")).getClientProperty(StudySelectionActions.class)==get(workspace,"summarySelection"),"summary pane not bound");
            call(workspace,"showConcepts");
            expandConcept((Container)get(workspace,"conceptList"),"운동량");
            List<StudyHtmlPane> conceptPanes=new ArrayList<>();collect((Container)get(workspace,"conceptList"),conceptPanes);
            check(!conceptPanes.isEmpty()&&conceptPanes.stream().allMatch(p->p.getClientProperty(StudySelectionActions.class)==uncheckedGet(workspace,"conceptSelection")),"concept pane not bound");
            JTextArea draft=(JTextArea)get(workspace,"question");draft.setText("작성 중인 질문");
            Path attachment=library.resolve("draft.png");((List<Path>)get(workspace,"tutorAttachments")).add(attachment);
            ((java.util.Set<Path>)get(workspace,"tutorPastedAttachments")).add(attachment);
            int[] opened={0};set(workspace,"tutorSideOpener",(Runnable)()->opened[0]++);
            String source="운동량 $\\vec{p}=m\\vec{v}$";
            call(workspace,"askSelectedStudy",new Class<?>[]{String.class},source);
            check(opened[0]==1&&held.commands.size()==1,"selection did not open tutor and submit exactly once");
            check(draft.getText().equals("작성 중인 질문")&&((List<Path>)get(workspace,"tutorAttachments")).equals(List.of(attachment)),"selection destroyed draft/attachment");
            check(((java.util.Set<Path>)get(workspace,"tutorPastedAttachments")).contains(attachment),"selection consumed draft attachment ownership");
            JsonObject request=null;
            for(Field field:held.commands.get(0).getClass().getDeclaredFields())if(field.getType()==JsonObject.class){field.setAccessible(true);request=(JsonObject)field.get(held.commands.get(0));}
            check(request!=null&&request.get("question").getAsString().equals("["+source+"]\n\n이 부분에 대해 상세히 설명해줘."),"actual tutor request lost selection/LaTeX");
            check(!request.has("attachmentSources"),"selection accidentally sent draft attachments");
            List<StudyHtmlPane> chatPanes=new ArrayList<>();collect((Container)get(workspace,"tutorMessages"),chatPanes);
            check(chatPanes.stream().anyMatch(p->!maths(p).isEmpty()),"selected formula became raw TeX in the user chat bubble");
            call(workspace,"askSelectedStudy",new Class<?>[]{String.class},source);
            check(held.commands.size()==1,"busy tutor accepted duplicate request");
        }finally {workspace.close();}
    }
    private static boolean expandConcept(Container root,String name) {
        for(Component child:root.getComponents()){
            if(child instanceof JButton button&&name.equals(button.getAccessibleContext().getAccessibleName())){button.doClick();return true;}
            if(child instanceof Container nested&&expandConcept(nested,name))return true;
        }
        return false;
    }
    private static final class HoldingExecutor extends AbstractExecutorService {
        final List<Runnable> commands=new ArrayList<>();private boolean stopped;
        @Override public void execute(Runnable command){if(stopped)throw new RejectedExecutionException();commands.add(command);}
        @Override public void shutdown(){stopped=true;}
        @Override public List<Runnable> shutdownNow(){stopped=true;return List.copyOf(commands);}
        @Override public boolean isShutdown(){return stopped;}
        @Override public boolean isTerminated(){return stopped;}
        @Override public boolean awaitTermination(long timeout,TimeUnit unit){return stopped;}
    }
    private static StudyHtmlPane pane(String markdown) {
        StudyHtmlPane pane=new StudyHtmlPane(true);pane.setEditable(false);
        pane.setText("<html><body>"+StudyMarkdown.render(markdown,16)+"</body></html>");return pane;
    }
    private static List<Element> maths(StudyHtmlPane pane) {
        List<Element> maths=new ArrayList<>();HTMLDocument document=(HTMLDocument)pane.getDocument();
        for(int i=0;i<document.getLength();) {
            Element e=document.getCharacterElement(i);
            if(e.getAttributes().getAttribute(HTML.Tag.SPAN) instanceof AttributeSet span&&span.getAttribute("data-study-tex")!=null)maths.add(e);
            i=e.getEndOffset();
        }
        return maths;
    }
    private static Point position(StudyHtmlPane pane,int offset)throws Exception {
        Rectangle box=pane.modelToView2D(offset).getBounds();return new Point(box.x,box.y+Math.max(1,box.height/2));
    }
    private static void mouse(Component pane,int id,Point p,int modifiers,int button){pane.dispatchEvent(new MouseEvent(pane,id,System.currentTimeMillis(),modifiers,p.x,p.y,0,0,1,false,button));}
    private static void layout(StudyHtmlPane pane){BufferedImage image=new BufferedImage(pane.getWidth(),pane.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();pane.paint(g);g.dispose();}
    private static String plain(StudyHtmlPane pane)throws Exception{return pane.getDocument().getText(0,pane.getDocument().getLength());}
    private static void collect(Container root,List<StudyHtmlPane> panes){for(Component c:root.getComponents())if(c instanceof StudyHtmlPane p)panes.add(p);else if(c instanceof Container nested)collect(nested,panes);}
    private static Object get(Object object,String name)throws Exception {Field f=object.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(object);}
    private static Object uncheckedGet(Object object,String name){try{return get(object,name);}catch(Exception e){throw new RuntimeException(e);}}
    private static void set(Object object,String name,Object value)throws Exception {Field f=object.getClass().getDeclaredField(name);f.setAccessible(true);f.set(object,value);}
    private static void call(Object object,String name)throws Exception{call(object,name,new Class<?>[]{});}
    private static void call(Object object,String name,Class<?>[] types,Object...arguments)throws Exception{Method m=object.getClass().getDeclaredMethod(name,types);m.setAccessible(true);m.invoke(object,arguments);}
    private static void check(boolean valid,String message){if(!valid)throw new AssertionError(message);}
}
