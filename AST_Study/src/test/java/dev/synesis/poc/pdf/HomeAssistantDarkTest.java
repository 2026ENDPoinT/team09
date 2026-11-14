package dev.synesis.poc.pdf;

import java.awt.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.concurrent.atomic.AtomicReference;
import javax.swing.*;
import javax.swing.text.html.*;

/** Offline instance isolation and stream fade completion; no windows or provider calls. */
public final class HomeAssistantDarkTest {
    static Object get(Object o,String name)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    static void set(Object o,String name,Object value)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);f.set(o,value);}
    static Object call(Object o,String name,Class<?>[] types,Object... args)throws Exception{Method m=o.getClass().getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(o,args);}
    static void check(boolean ok,String reason){if(!ok)throw new AssertionError(reason);}
    public static void main(String[] args)throws Exception {
        System.setProperty("synesis.dataRoot",Files.createTempDirectory("assistant-dark-").toString());
        HomeAssistant[] home=new HomeAssistant[1];Object[] answer=new Object[1];
        SwingUtilities.invokeAndWait(()->{try {
            home[0]=new HomeAssistant();home[0].setSize(1120,800);home[0].doLayout();
            JTextArea input=(JTextArea)get(home[0],"input");check(input.getForeground().equals(AssistantChatTheme.TEXT),"input text");
            JPanel messages=(JPanel)get(home[0],"messages");check(messages.getBackground().equals(AssistantChatTheme.BACKGROUND),"chat background");
            answer[0]=call(home[0],"addBubble",new Class[]{String.class,boolean.class},"",false);
            set(home[0],"answerBubble",answer[0]);set(home[0],"busy",true);
            set(home[0],"completedAnswer","안녕");set(home[0],"completionStatus","완료");
            ((AtomicReference<String>)get(home[0],"pending")).set("안녕");
            call(home[0],"reveal",new Class[]{});
            check((boolean)get(home[0],"busy"),"completion cut off the final fade");
            TutorStreamFade fade=(TutorStreamFade)get(answer[0],"streamFade");
            check(fade.active(System.currentTimeMillis()),"new text has no fade");
            Object renderer=get(answer[0],"renderedAnswer");check(get(renderer,"fill").equals(AssistantChatTheme.SURFACE),"answer background");
            StudyHtmlPane pane=new StudyHtmlPane(true);AssistantChatTheme.configure(pane);
            pane.setText(SummarySkin.formulaDocument("<p>본문 <code>value</code></p><pre>int value = 2;</pre>",14));
            String css=((HTMLDocument)pane.getDocument()).getStyleSheet().getRule("body").getAttribute(CSS.Attribute.COLOR).toString();
            check(css.equals("#f3f5f9"),"dark body color: "+css);
            StudyHtmlPane light=new StudyHtmlPane(true);light.setText(SummarySkin.formulaDocument("<p>본문</p>",14));
            String lightCss=((HTMLDocument)light.getDocument()).getStyleSheet().getRule("body").getAttribute(CSS.Attribute.COLOR).toString();
            check(lightCss.equals("#252629"),"dark palette leaked into study renderer");
            TutorStreamFade colors=new TutorStreamFade(0x292e38,0xf3f5f9);colors.accept("글",1000);
            check(colors.decorate("글",1000).contains("#292e38"),"fade does not start at background");
            check(!colors.decorate("글",1120).equals(colors.decorate("글",1000)),"fade color not advancing");
            check(colors.decorate("글",1240).equals("글"),"fade never clears");
            TutorStreamFade soft=new TutorStreamFade(0x292e38,0xf3f5f9,680,true);soft.accept("글",1000);
            check(soft.active(1500),"personal assistant fade ends too early");
            check(!soft.active(1680),"personal assistant fade never ends");
        }catch(Exception e){throw new RuntimeException(e);}});
        Thread.sleep(740);
        SwingUtilities.invokeAndWait(()->{try {
            call(answer[0],"animateText",new Class[]{});call(home[0],"reveal",new Class[]{});
            check(!(boolean)get(home[0],"busy"),"completed answer did not release after fade");
        }catch(Exception e){throw new RuntimeException(e);}finally{home[0].close();}});
        System.out.println("HomeAssistantDarkTest OK · local palette, light isolation, background fade and completion drain");
    }
}
