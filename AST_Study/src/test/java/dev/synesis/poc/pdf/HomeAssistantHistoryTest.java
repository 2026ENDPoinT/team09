package dev.synesis.poc.pdf;
import com.google.gson.*;
import javax.swing.*;
import java.nio.file.*;
import java.util.concurrent.*;
import static dev.synesis.poc.pdf.HomeAssistantMotionTest.*;
public final class HomeAssistantHistoryTest {
 static HomeAssistant view;static AssistantConversations store;
 static void edt(Runnable action)throws Exception{SwingUtilities.invokeAndWait(action);}
 static void flush()throws Exception{((ExecutorService)get(view,"worker")).submit(()->{}).get(10,TimeUnit.SECONDS);edt(()->{});}
 static void select(String id,int count)throws Exception{edt(()->{try{call(view,"loadConversation",new Class[]{String.class,int.class},id,count);}catch(Exception e){throw new RuntimeException(e);}});flush();}
 public static void main(String[] args)throws Exception{
  System.setProperty("synesis.dataRoot",Files.createTempDirectory("assistant-history-ui-").toString());
  edt(()->{view=new HomeAssistant();view.setSize(1120,800);try{set(view,"expanded",true);((JPanel)get(view,"card")).setVisible(true);view.doLayout();}catch(Exception e){throw new RuntimeException(e);}});
  try{
   store=new AssistantConversations((Path)get(view,"folder"));JsonObject first=AssistantConversationsTest.snapshot("alpha",1,40);first.getAsJsonObject("receipts").addProperty("40000","0.25 크레딧");first.getAsJsonObject("deliveryHistory").addProperty("40000",39900);store.save(first);store.save(AssistantConversationsTest.snapshot("beta",41,1));
   select("alpha",30);
   edt(()->{try{
    check(get(view,"session").equals("alpha"),"session restored");check((boolean)get(view,"ready"),"controls ready after switch");JPanel messages=(JPanel)get(view,"messages");check(messages.getComponent(0) instanceof JButton,"long flow has older messages control");check(messages.getComponentCount()==122,"restoration bypasses live 30-turn widget pruning");
    check(((JsonObject)get(view,"receipts")).get("40000").getAsString().equals("0.25 크레딧"),"credit metadata restored");
    check(((JsonObject)get(view,"deliveryHistory")).get("40000").getAsLong()==39900,"read receipt restored");
    HomeAssistantMotionTest.layout(view);JButton history=(JButton)get(view,"history"),fresh=(JButton)get(view,"fresh");check(history.getParent()==fresh.getParent()&&history.getX()<fresh.getX(),"history button left of new chat");
   }catch(Exception e){throw new RuntimeException(e);}});
   select("alpha",60);edt(()->{try{check(((JPanel)get(view,"messages")).getComponentCount()==160,"older messages can all be expanded");call(view,"resetConversation",new Class[]{});}catch(Exception e){throw new RuntimeException(e);}});flush();
   check(store.list().size()==2,"new blank chat preserves both previous flows");check(AssistantConversations.turns(store.load("alpha")).size()==40,"reset never deletes opened conversation");
   select("beta",30);check(get(view,"session").equals("beta"),"another flow selectable after reset");
   System.out.println("HomeAssistantHistoryTest OK · toolbar position, session switch, metadata, pagination, new-chat preservation");
  }finally{edt(view::close);}
 }
}
