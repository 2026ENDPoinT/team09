package dev.synesis.poc.pdf;
import javax.swing.*;
import java.awt.*;
import java.nio.file.*;
import java.awt.image.BufferedImage;
import javax.imageio.ImageIO;
import java.lang.reflect.*;
import java.util.concurrent.atomic.AtomicReference;

/** Real chat components with offline SSE snapshots; never calls send or a provider. */
public final class HomeAssistantConversationTest {
    static Object get(Object o,String name)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    static void set(Object o,String name,Object value)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);f.set(o,value);}
    static Object call(Object o,String name,Class<?>[] types,Object... args)throws Exception{Method m=o.getClass().getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(o,args);}
    static void check(boolean ok,String reason){if(!ok)throw new AssertionError(reason);}
    static Font fontAt(javax.swing.text.View view,int offset){
        if(view instanceof javax.swing.text.GlyphView glyph&&offset>=view.getStartOffset()&&offset<view.getEndOffset())return glyph.getFont();
        for(int i=0;i<view.getViewCount();i++){Font font=fontAt(view.getView(i),offset);if(font!=null)return font;}return null;
    }
    static StudyHtmlPane paneContaining(Container container,String text)throws Exception{
        for(Component c:container.getComponents()){
            if(c instanceof StudyHtmlPane pane&&pane.getDocument().getText(0,pane.getDocument().getLength()).contains(text))return pane;
            if(c instanceof Container nested){StudyHtmlPane found=paneContaining(nested,text);if(found!=null)return found;}
        }return null;
    }
    static void layout(Container parent){parent.doLayout();for(Component c:parent.getComponents())if(c instanceof Container nested)layout(nested);}
    static void render(HomeAssistant view,Path path)throws Exception{
        for(int i=0;i<3;i++)layout(view);
        JPanel messages=(JPanel)get(view,"messages");for(Component c:messages.getComponents())if(c.getClass().getSimpleName().equals("ChatBubble"))set(c,"opacity",1f);
        BufferedImage image=new BufferedImage(1120,800,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();g.setColor(new Color(0xF2F5F9));g.fillRect(0,0,1120,800);view.printAll(g);g.dispose();ImageIO.write(image,"png",path.toFile());
    }
    public static void main(String[] args)throws Exception{
        Path temp=Files.createTempDirectory("assistant-conversation-");System.setProperty("synesis.dataRoot",temp.resolve("absent").toString());
        Path out=Path.of("build/home-assistant-design-20261024");Files.createDirectories(out);
        SwingUtilities.invokeAndWait(()->{
            HomeAssistant view=new HomeAssistant();
            try{
                view.setSize(1120,800);set(view,"expanded",true);((JPanel)get(view,"card")).setVisible(true);view.doLayout();
                JPanel messages=(JPanel)get(view,"messages");messages.removeAll();
                call(view,"addBubble",new Class[]{String.class,boolean.class},"내일 오후에 두 시간 정도 복습하고 싶어요. 어떻게 공부하면 좋을까요?",true);
                Object answer=call(view,"addBubble",new Class[]{String.class,boolean.class},"",false);set(view,"answerBubble",answer);call(answer,"thinking",new Class[]{});
                check((boolean)get(answer,"waiting"),"thinking state missing");render(view,out.resolve("thinking.png"));
                String text="먼저 오늘 배운 내용을 짧게 떠올린 뒤, 헷갈린 부분에 시간을 더 배분해요.\\n\\n처음 20분은 핵심 개념 복습에, 다음 60분은 문제 풀이에 써보세요. 마지막에는 틀린 이유를 정리해요.".replace("\\n","\n");
                set(view,"busy",true);set(view,"completedAnswer",text);set(view,"completionStatus","이번 답변 0.04 크레딧");
                @SuppressWarnings("unchecked") AtomicReference<String> pending=(AtomicReference<String>)get(view,"pending");pending.set(text);
                call(view,"reveal",new Class[]{});
                String first=(String)get(answer,"shown");
                check(!first.isEmpty()&&!first.equals(text),"short answer dumped in one frame");
                check(!(boolean)get(answer,"waiting"),"thinking did not yield to first delta");
                render(view,out.resolve("streaming.png"));
                Object streamingRenderer=get(answer,"renderedAnswer");
                StudyHtmlPane streamingPane=paneContaining((Container)streamingRenderer,"먼저");
                String streamingPlain=streamingPane.getDocument().getText(0,streamingPane.getDocument().getLength());
                Font streamingFont=fontAt(streamingPane.getUI().getRootView(streamingPane),streamingPlain.indexOf("먼저"));
                // Production ticks are 40ms apart; the Markdown throttle and glyph fade
                // need wall time even when this test runs on a fast headless machine.
                long revealDeadline=System.nanoTime()+8_000_000_000L;int ticks=1;while((boolean)get(view,"busy")&&System.nanoTime()<revealDeadline){ticks++;call(view,"reveal",new Class[]{});Thread.sleep(20);}
                check(!(boolean)get(view,"busy"),"final event never drained");
                JPanel surface=(JPanel)get(answer,"surface");check(surface.getComponent(0) instanceof PdfWorkspace.RoundedTutorBubble,"shared mentor renderer missing");
                check(surface.getComponent(0)==streamingRenderer,"completion replaced streaming renderer");
                StudyHtmlPane html=paneContaining(surface,"60분");String plain=html.getDocument().getText(0,html.getDocument().getLength());Files.writeString(out.resolve("final-body.txt"),plain);check(plain.replaceAll("\\s+", "").contains("60분"),"final answer truncated");
                JTextPane live=(JTextPane)get(answer,"live");
                html.setSize(380,Short.MAX_VALUE);html.modelToView2D(plain.indexOf("먼저"));
                Font finishedFont=fontAt(html.getUI().getRootView(html),plain.indexOf("먼저"));
                check(finishedFont!=null,"final prose view missing");
                check(finishedFont.getFontName().equals(live.getFont().getFontName()),"completion changed font face: "+finishedFont+" vs "+live.getFont());
                check(finishedFont.getSize()==live.getFont().getSize(),"completion changed font size");
                check(finishedFont.equals(streamingFont),"completion changed actual rendered font");
                String rich="## 복습\n\n> **핵심 관계식**\n>\n> $$p=mv$$\n>\n> $$"+String.join("+",java.util.Collections.nCopies(35,"p_{i}"))+"=0$$\n\n"
                    +"1. 개념을 확인해요.\n2. 계산해요.\n\n| 구분 | 의미 |\n|---|---|\n| 운동량 | 질량과 속도의 곱 |\n\n```java\nint total = 2;\n```\n\n인라인 `total`과 $x^2$도 표시해요.";
                call(answer,"finish",new Class[]{String.class},rich);render(view,out.resolve("rich-content.png"));
                java.util.Map<?,?> groups=(java.util.Map<?,?>)get(streamingRenderer,"readingGroups");
                check(groups.size()>=2,"mentor formula/table/code groups missing");
                check(paneContaining(surface,"int total = 2;")!=null,"code block missing");
                int groupCount=groups.size();view.setSize(500,800);view.doLayout();layout(view);
                check(groups.size()==groupCount,"narrow reflow lost formula/table/code groups");
                render(view,out.resolve("complete.png"));
                // The shared mentor class initializes portable display preferences in this temp root.
                check(!Files.exists(temp.resolve("absent/account"))&&!Files.exists(temp.resolve("absent/library")),"test wrote conversation or library data");
                System.out.println("HomeAssistantConversationTest OK · first tick "+first.codePointCount(0,first.length())+" chars · drained "+ticks+" ticks");
            }catch(Exception e){throw new RuntimeException(e);}finally{view.close();}
        });try(var paths=Files.walk(temp)){for(Path path:paths.sorted(java.util.Comparator.reverseOrder()).toList())Files.delete(path);}
    }
}
