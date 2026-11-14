package dev.synesis.poc.pdf;

import javax.swing.SwingUtilities;
import java.awt.geom.Rectangle2D;

/** Keep a formula's sentence continuation together, with native width-based wrapping. */
public final class FormulaContinuationTest {
    public static void main(String[] args)throws Exception {
        try {SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception e){throw new RuntimeException(e);}});}
        catch(Throwable failure){failure.printStackTrace();System.exit(1);}
        System.out.println("FormulaContinuationTest passed");
        System.exit(0);
    }
    private static void run()throws Exception {
        String rendered=StudyMarkdown.renderWithScrollableMath("주어진 값\n\n$$a=123456$$\n\n를 대입하면\n\n$$b=4$$\n\n예요.\n이어서 계산해요.",18);
        var presentation=SummarySkin.prepare(rendered);
        String html=SummarySkin.document("",presentation.body(),18);
        require(!html.contains("<p>를 대입하면")&&!html.contains("<p>예요."),"continuation stays with its equation");
        require(html.contains("이어서 계산해요."),"following explanation survives");
        StudyHtmlPane pane=new StudyHtmlPane(true);pane.setReadingSkin(true);pane.setText(html);
        String text=pane.getDocument().getText(0,pane.getDocument().getLength());
        int math=text.indexOf("a="),tail=text.indexOf("를 대입하면");
        require(math>=0&&tail>math,"math and suffix remain selectable");
        for(int width:new int[]{900,230,900}) {
            pane.setSize(width,1000);pane.getUI().getRootView(pane).setSize(width,1000);
            Rectangle2D m=pane.modelToView2D(math),t=pane.modelToView2D(tail);
            boolean same=t.getY()<m.getMaxY()-2;
            require(width==230?!same:same,"responsive continuation at width "+width+": "+m+" / "+t);
        }
        String literal=SummarySkin.document("",StudyMarkdown.render("```text\n$$a=1$$\n\n를 대입하면\n```",18),18);
        require(literal.contains("$$a=1$$"),"code stays literal");
        String heading=SummarySkin.document("",StudyMarkdown.renderWithScrollableMath("$$a=1$$\n\n## 를 대입하면",18),18);
        require(heading.contains("<h2>를 대입하면"),"headings are not absorbed");
    }
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
}
