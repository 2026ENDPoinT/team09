package dev.synesis.poc.pdf;

import com.google.gson.JsonParser;
import java.awt.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.List;
import java.util.function.Consumer;
import javax.swing.*;

/** Replays partial Markdown through the real bubble/scroll/table layout, offline. */
public final class TutorStreamingTableTest {
    public static void main(String[] args) throws Exception {
        String answer=args.length==0
            ?"공식 자료의 범주를 구분해요.\n\n| 범주 | 비율 | 정의 |\n|---|---|---|\n"
                +"| 임시적 일자리 | 4.3% | 계속될 것으로 기대되지 않는 일자리 |\n"
                +"| 파견업체 근로자 | 0.6% | 파견업체에서 급여를 받는 근로자 |\n\n마지막 문장까지 표시해요."
            :JsonParser.parseString(Files.readString(Path.of(args[0]))).getAsJsonObject().get("answer").getAsString();
        SwingUtilities.invokeAndWait(()->{
            try {
                StudyHtmlPane mounted=new StudyHtmlPane(true);mounted.setReadingSkin(true);
                mounted.setText("<html><body>이전 본문</body></html>");
                JScrollPane viewport=new JScrollPane(mounted);viewport.setSize(380,400);viewport.doLayout();
                var old=mounted.getDocument();
                int[] partialEvents={0};
                old.addDocumentListener(new javax.swing.event.DocumentListener(){
                    public void insertUpdate(javax.swing.event.DocumentEvent e){partialEvents[0]++;mounted.getPreferredSize();}
                    public void removeUpdate(javax.swing.event.DocumentEvent e){partialEvents[0]++;mounted.getPreferredSize();}
                    public void changedUpdate(javax.swing.event.DocumentEvent e){}
                });
                String table="<html><body><table><tr><th>범주</th><th>비중</th></tr>"
                    +"<tr><td>원문을 보존하는 표</td><td>4.3%</td></tr>".repeat(200)+"</table>마지막 문장</body></html>";
                mounted.setText(table);
                if(partialEvents[0]!=0 || mounted.getDocument()==old)
                    throw new AssertionError("Mounted document exposed partial table edits");
                String plain=mounted.getDocument().getText(0,mounted.getDocument().getLength());
                if(!plain.contains("마지막 문장")||!plain.contains("4.3%"))throw new AssertionError("Content lost");
                Class<?> type=Class.forName("dev.synesis.poc.pdf.PdfWorkspace$RoundedTutorBubble");
                Constructor<?> ctor=type.getDeclaredConstructor(String.class,boolean.class,int.class,int.class,Consumer.class,List.class);
                ctor.setAccessible(true);
                Method update=type.getDeclaredMethod("updateContent",String.class,int.class,int.class);
                update.setAccessible(true);
                for(int width:new int[]{250,380,574}) {
                    JPanel bubble=(JPanel)ctor.newInstance("<p></p>",false,width,16,(Consumer<String>)s->{},List.of());
                    for(int end=1;end<=answer.length();end++) {
                        String html=StudyMarkdown.renderWithScrollableMath(answer.substring(0,end),16,false,width-32);
                        update.invoke(bubble,html,width,16);
                        bubble.setSize(width,Math.max(1,bubble.getPreferredSize().height));
                        layout(bubble);
                    }
                }
            }catch(Exception failure){throw new RuntimeException(failure);}
        });
        System.out.println("TutorStreamingTableTest OK: all prefixes at 3 widths");
        System.exit(0);
    }
    private static void layout(Container parent) {
        parent.doLayout();
        for(Component child:parent.getComponents())if(child instanceof Container container)layout(container);
    }
}
