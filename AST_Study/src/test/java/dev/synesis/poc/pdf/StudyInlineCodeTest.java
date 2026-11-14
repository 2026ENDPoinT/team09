package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.image.BufferedImage;
import javax.swing.*;
import javax.swing.text.View;

public final class StudyInlineCodeTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            try {
                StudyHtmlPane pane=new StudyHtmlPane(true);pane.setReadingSkin(true);
                pane.setText(SummarySkin.formulaDocument("<p>앞 <code>std::cin</code> 뒤</p>",14));
                pane.setSize(360,160);View root=pane.getUI().getRootView(pane);root.setSize(360,160);
                View inline=find(root);
                if(inline==null)throw new AssertionError("inline code renderer missing");
                String copied=pane.getDocument().getText(0,pane.getDocument().getLength());
                if(!copied.contains("앞 std::cin 뒤"))throw new AssertionError("code text changed");
                BufferedImage image=new BufferedImage(230,60,BufferedImage.TYPE_INT_RGB);
                Graphics2D g=image.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,230,60);
                inline.paint(g,new Rectangle(10,10,200,30));g.dispose();
                if((image.getRGB(10,10)&0xffffff)!=0xffffff)throw new AssertionError("square corner remains");
                if((image.getRGB(110,11)&0xffffff)!=0xf2f7ff)throw new AssertionError("inline paper color changed");
                pane.setText(SummarySkin.formulaDocument("<pre><code>std::cin</code></pre>",14));
                root=pane.getUI().getRootView(pane);root.setSize(360,160);
                if(find(root)!=null)throw new AssertionError("code block treated as inline");
            } catch(Exception e){throw new RuntimeException(e);}
        });
        System.out.println("StudyInlineCodeTest OK");System.exit(0);
    }
    private static View find(View view) {
        if(view instanceof StudyInlineCode)return view;
        for(int i=0;i<view.getViewCount();i++){View found=find(view.getView(i));if(found!=null)return found;}
        return null;
    }
}
