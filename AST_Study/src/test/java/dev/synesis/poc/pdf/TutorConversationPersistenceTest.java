package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import javax.swing.*;
import org.apache.pdfbox.pdmodel.*;

/** PDF-local history, model context and explicit reset; no provider or app window. */
public final class TutorConversationPersistenceTest {
    static Object get(Object target,String name)throws Exception{Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(target);}
    static void set(Object target,String name,Object value)throws Exception{Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);f.set(target,value);}
    static Object call(Object target,String name,Class<?>[] types,Object...args)throws Exception{Method m=target.getClass().getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(target,args);}
    static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    static void drain(PdfWorkspace workspace)throws Exception{((ExecutorService)get(workspace,"files")).submit(()->{}).get(5,TimeUnit.SECONDS);}
    public static void main(String[]args)throws Exception{
        Path root=Files.createTempDirectory("tutor-history-");System.setProperty("synesis.dataRoot",root.resolve("app-data").toString());
        Path pdf=root.resolve("lesson.pdf");try(PDDocument doc=new PDDocument()){doc.addPage(new PDPage());doc.save(pdf.toFile());}
        PdfWorkspace[] views=new PdfWorkspace[2];PdfSource source=PdfSource.open(pdf,root.resolve("library"));
        SwingUtilities.invokeAndWait(()->{try{
            views[0]=new PdfWorkspace(false,root.resolve("library"));set(views[0],"source",source);
            @SuppressWarnings("unchecked") List<Object> turns=(List<Object>)get(views[0],"conversation");
            Class<?> type=Class.forName("dev.synesis.poc.pdf.PdfWorkspace$TutorTurn");Constructor<?> ctor=type.getDeclaredConstructor(String.class,String.class,List.class);ctor.setAccessible(true);
            @SuppressWarnings("unchecked") Map<String,JsonObject> answers=(Map<String,JsonObject>)get(views[0],"tutorAnswers");
            for(int n=0;n<15;n++){Object turn=ctor.newInstance("질문 "+n,"marker"+n,List.of());turns.add(turn);JsonObject answer=new JsonObject();answer.addProperty("answer","답변 "+n);answers.put("marker"+n,answer);}
            JsonObject memory=new JsonObject();JsonArray history=new JsonArray();JsonObject last=new JsonObject();last.addProperty("question","질문 14");last.addProperty("answer","답변 14");history.add(last);memory.add("turns",history);set(views[0],"tutorMemory",memory);
            call(views[0],"saveTutorConversation",new Class[]{});
            // Clearing a view for navigation must not delete its PDF's saved history.
            call(views[0],"resetTutor",new Class[]{});
        }catch(Exception e){throw new RuntimeException(e);}});
        drain(views[0]);JsonObject saved=TutorConversationStore.read(source.folder);
        check(saved.getAsJsonArray("turns").size()==15,"history truncated");
        check(TutorConversationStore.read(root.resolve("another-pdf")).isEmpty(),"history leaked across PDFs");
        SwingUtilities.invokeAndWait(()->{try{
            views[1]=new PdfWorkspace(false,root.resolve("library"));set(views[1],"source",PdfSource.open(pdf,root.resolve("library")));
            call(views[1],"restoreTutorConversation",new Class[]{JsonObject.class},saved);
            check(((List<?>)get(views[1],"conversation")).size()==15,"reopen lost history");
            check(((JsonObject)get(views[1],"tutorMemory")).getAsJsonArray("turns").size()==1,"model context lost");
            check(((Map<?,?>)get(views[1],"tutorAnswers")).size()==15,"answer cards lost");
            call(views[1],"startNewTutorChat",new Class[]{int.class},1);
            check(((List<?>)get(views[1],"conversation")).size()==15,"cancel deleted history");
            call(views[1],"startNewTutorChat",new Class[]{int.class},JOptionPane.CLOSED_OPTION);
            check(((List<?>)get(views[1],"conversation")).size()==15,"dialog close deleted history");
            call(views[1],"startNewTutorChat",new Class[]{int.class},0);
            check(((List<?>)get(views[1],"conversation")).isEmpty(),"new chat retained old turns");
            check(((JsonObject)get(views[1],"tutorMemory")).isEmpty(),"new chat retained model context");
        }catch(Exception e){throw new RuntimeException(e);}});
        drain(views[1]);JsonObject cleared=TutorConversationStore.read(source.folder);
        check(cleared.getAsJsonArray("turns").isEmpty(),"new chat not persisted");
        // Don't allow the stale fixture view to save over the freshly reset file on close.
        SwingUtilities.invokeAndWait(()->{try{set(views[0],"source",null);views[0].close();views[1].close();}catch(Exception e){throw new RuntimeException(e);}});
        source.close();System.out.println("TutorConversationPersistenceTest OK · PDF isolation, 15 turns, answers/context restored, explicit reset persisted");System.exit(0);
    }
}
