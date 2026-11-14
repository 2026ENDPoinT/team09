package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.image.BufferedImage;
import javax.swing.*;

/** The hint is bounded paint-only feedback; no window, drag session or model is created. */
public final class LibraryMoveHintTest {
    private static final class Surface extends JPanel {
        int changes;Rectangle dirty;
        @Override public void repaint(int x,int y,int width,int height){changes++;dirty=new Rectangle(x,y,width,height);}
    }
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            Surface surface=new Surface();surface.setSize(480,360);LibraryMoveHint hint=new LibraryMoveHint();
            check(LibraryMoveHint.destinationText("홈 화면").equals("홈 화면으로 이동"),"home destination label");
            check(LibraryMoveHint.destinationText("강의").equals("강의로 이동"),"vowel ending label");
            check(LibraryMoveHint.destinationText("파일").equals("파일로 이동"),"rieul ending label");
            for(Point point:new Point[]{new Point(220,180),new Point(475,355),new Point(2,2),new Point(475,2)}) {
                hint.show(surface,"홈 화면으로 이동",point,new Dimension(160,160));
                check(hint.visible(),"valid target hint missing");
                check(new Rectangle(surface.getSize()).contains(hint.bounds()),"hint leaves library bounds");
                check(!hint.bounds().contains(point),"hint hides pointer");
            }
            hint.show(surface,"영어로 이동",new Point(220,180),new Dimension(160,160));int before=surface.changes;
            hint.show(surface,"국어로 이동",new Point(220,180),new Dimension(160,160));
            check(surface.changes>before && hint.caption().equals("국어로 이동"),"same-size destination text did not repaint");
            hint.show(surface,"긴 폴더 이름 😀".repeat(40)+"으로 이동",new Point(220,180),new Dimension(160,160));
            check(hint.bounds().width<=270,"long label grows without a bound");
            BufferedImage pixels=new BufferedImage(480,360,BufferedImage.TYPE_INT_ARGB);Graphics2D g=pixels.createGraphics();hint.paint(g);g.dispose();
            Rectangle bounds=hint.bounds();check(pixels.getRGB(bounds.x+5,bounds.y+10)!=0,"hint background/icon not painted");
            hint.clear(surface);check(!hint.visible()&&hint.caption().isEmpty(),"hint retained after leave/cancel");
            hint.show(surface,"홈 화면으로 이동",new Point(-1,10),new Dimension());check(!hint.visible(),"hint remains outside library");
        });
        System.out.println("LibraryMoveHintTest OK: destination labels, edge placement, bounded text, repaint, leave/cancel cleanup");
        System.exit(0);
    }
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
