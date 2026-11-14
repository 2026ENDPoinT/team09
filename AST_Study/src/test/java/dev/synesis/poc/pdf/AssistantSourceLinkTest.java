package dev.synesis.poc.pdf;

import javax.swing.*;
import javax.swing.text.html.*;
import java.awt.*;

/** Actual assistant renderer: persisted Markdown source links remain clickable. */
public final class AssistantSourceLinkTest {
    static int links(Container c){
        int count=0;
        for(Component child:c.getComponents()){
            if(child instanceof StudyHtmlPane pane){
                HTMLDocument doc=(HTMLDocument)pane.getDocument();
                for(HTMLDocument.Iterator it=doc.getIterator(HTML.Tag.A);it.isValid();it.next()){
                    if("https://www.python.org/downloads/".equals(it.getAttributes().getAttribute(HTML.Attribute.HREF))){
                        if(pane.getHyperlinkListeners().length==0)throw new AssertionError("source has no click handler");count++;
                    }
                }
            }else if(child instanceof Container nested)count+=links(nested);
        }return count;
    }
    public static void main(String[] args)throws Exception{
        System.setProperty("synesis.dataRoot",java.nio.file.Files.createTempDirectory("assistant-sources-").toString());
        SwingUtilities.invokeAndWait(()->{
            String markdown="공식 자료로 확인했어요. [1]\n\n**출처**\n- [1. Python 공식 발표](<https://www.python.org/downloads/>)";
            JPanel bubble=PdfWorkspace.assistantAnswerBubble(AssistantSources.render(markdown,14,388),420,14,ignored->{});
            if(links(bubble)<1)throw new AssertionError("verified source link missing");
            System.out.println("AssistantSourceLinkTest OK · source URL and click handler preserved in actual renderer");
        });
    }
}
