package dev.synesis.poc.pdf;

import javax.swing.*;
import javax.swing.text.*;
import javax.swing.text.html.*;
import java.awt.*;
import java.awt.image.BufferedImage;

/** Offscreen layout/copy regression: never opens an application window. */
public final class StudyCodeBlockTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception error){throw new RuntimeException(error);}});
        System.out.println("StudyCodeBlockTest passed: bounded padding, border, wrapped visual lines, original text, syntax colors.");
        System.exit(0);
    }
    private static void run()throws Exception {
        String code="int add(int a, int b); // declaration\n\nint add(int a, int b) {\n    return a + b;\n}\n";
        StudyHtmlPane pane=new StudyHtmlPane(true);pane.setReadingSkin(true);
        pane.setText(SummarySkin.formulaDocument("<pre><code>\n\n"+code+"\n</code></pre>",14));
        layout(pane,310);
        Element pre=pre(pane);String copied=pane.getDocument().getText(pre.getStartOffset(),pre.getEndOffset()-pre.getStartOffset());
        check(copied.equals(code),"Code contents changed: "+copied.replace("\n","\\n"));
        int start=pre.getStartOffset();Rectangle first=pane.modelToView2D(start).getBounds();
        check(first.y<=24,"Excess top padding: "+first.y);
        int body=code.indexOf("    return");Rectangle indent=pane.modelToView2D(start+body+4).getBounds();
        check(indent.x>first.x+8,"Nested indentation lost: first="+first+" indent="+indent);
        BufferedImage image=new BufferedImage(310,pane.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();
        g.setColor(Color.WHITE);g.fillRect(0,0,image.getWidth(),image.getHeight());pane.paint(g);g.dispose();
        boolean border=false,color=false;
        for(int y=0;y<image.getHeight();y++)for(int x=0;x<image.getWidth();x++) {
            Color c=new Color(image.getRGB(x,y));
            if((x<8 || y<8) && c.getRed()<65&&c.getGreen()<65&&c.getBlue()<65)border=true;
            if(c.getBlue()>c.getGreen()+25&&c.getRed()>c.getGreen()+10)color=true;
        }
        check(border,"Black outline missing");check(color,"Syntax color missing");
        String longLine="    int result = firstArgument + secondArgument + thirdArgument + fourthArgument + fifthArgument;\n";
        pane.setText(SummarySkin.formulaDocument("<pre><code>"+longLine+"</code></pre>",14));layout(pane,260);
        pre=pre(pane);start=pre.getStartOffset();
        check(pane.modelToView2D(start+longLine.length()-2).getY()>pane.modelToView2D(start).getY(),"Long line does not wrap");
        check(pane.getDocument().getText(start,pre.getEndOffset()-start).equals(longLine),"Soft wrapping inserted copy newlines");
        check(pane.getUI().getRootView(pane).getMinimumSpan(View.X_AXIS)<=260,"Code forces horizontal overflow");
        String tabs="void main() {\n\tint a = 3;\n\t\tint b = 4;\n    int c = 5;\n\t    int d = 6;\n}\n";
        pane.setText(SummarySkin.formulaDocument("<pre><code>"+tabs+"</code></pre>",14));layout(pane,600);
        pre=pre(pane);start=pre.getStartOffset();
        double tabX=pane.modelToView2D(start+tabs.indexOf("int a")).getX();
        double spacesX=pane.modelToView2D(start+tabs.indexOf("int c")).getX();
        double nestedX=pane.modelToView2D(start+tabs.indexOf("int b")).getX();
        double mixedX=pane.modelToView2D(start+tabs.indexOf("int d")).getX();
        check(Math.abs(tabX-spacesX)<2,"A tab does not align with four spaces: "+tabX+" / "+spacesX);
        check(nestedX>tabX+12,"Nested tabs are not indented");
        check(Math.abs(nestedX-mixedX)<2,"Mixed tabs and spaces are inconsistent");
        check(pane.getDocument().getText(start,pre.getEndOffset()-start).equals(tabs),"Tabs changed in copied code");
        String inlineTabs="int a;\tint b;\n        int c;\n";
        pane.setText(SummarySkin.formulaDocument("<pre><code>"+inlineTabs+"</code></pre>",14));layout(pane,600);
        pre=pre(pane);start=pre.getStartOffset();
        double afterToken=pane.modelToView2D(start+inlineTabs.indexOf("int b")).getX();
        double eightSpaces=pane.modelToView2D(start+inlineTabs.indexOf("int c")).getX();
        check(Math.abs(afterToken-eightSpaces)<2,"Tab after a colored token lost the shared column grid");
        layout(pane,220);pre=pre(pane);start=pre.getStartOffset();
        check(pane.getDocument().getText(start,pre.getEndOffset()-start).equals(inlineTabs),"Resize rewrites code tabs");
        check(StudyCodeBlock.decorate("<p>plain <code>int</code></p>").equals("<p>plain <code>int</code></p>"),"Inline prose changed");
        check(StudyCodeBlock.decorate("<pre><code>&lt;x&gt; &amp; &#39;value&#39;</code></pre>").contains("&#39;"),"Entity corrupted");
    }
    private static Element pre(StudyHtmlPane pane){ElementIterator it=new ElementIterator(pane.getDocument());for(Element e=it.first();e!=null;e=it.next())if(e.getAttributes().getAttribute(StyleConstants.NameAttribute)==HTML.Tag.PRE)return e;throw new AssertionError("Missing PRE");}
    private static void layout(StudyHtmlPane pane,int width){pane.setSize(width,3000);View root=pane.getUI().getRootView(pane);root.setSize(width,3000);int h=(int)Math.ceil(root.getPreferredSpan(View.Y_AXIS));pane.setSize(width,h);root.setSize(width,h);}
    private static void check(boolean okay,String message){if(!okay)throw new AssertionError(message);}
}
