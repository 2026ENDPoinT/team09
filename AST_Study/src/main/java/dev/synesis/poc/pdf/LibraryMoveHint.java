package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.LibraryDesign;
import java.awt.*;
import javax.swing.JComponent;

/** Pointer-following move feedback, painted in the library layer without windows, images or timers. */
final class LibraryMoveHint {
    private static final Font FONT=LibraryDesign.font(Font.PLAIN,11);
    private String caption="",shown="";
    private Rectangle bounds=new Rectangle();

    boolean visible(){return !bounds.isEmpty();}
    String caption(){return caption;}
    Rectangle bounds(){return new Rectangle(bounds);}

    static String destinationText(String name){
        if(name==null||name.isBlank())return "여기로 이동";
        int last=name.codePointBefore(name.length()),ending=last>=0xac00&&last<=0xd7a3?(last-0xac00)%28:0;
        return name+(ending!=0&&ending!=8?"으로 이동":"로 이동");
    }

    void show(JComponent surface,String text,Point pointer,Dimension preview){
        if(!new Rectangle(0,0,surface.getWidth(),surface.getHeight()).contains(pointer)){clear(surface);return;}
        FontMetrics fm=surface.getFontMetrics(FONT);
        boolean changed=!text.equals(caption);
        if(changed){
            caption=text;shown=text;
            while(shown.length()>1&&fm.stringWidth(shown)>220)shown=shown.substring(0,shown.offsetByCodePoints(shown.length(),-1));
            if(!shown.equals(text))shown=shown.stripTrailing()+"…";
        }
        int width=Math.min(surface.getWidth()-12,fm.stringWidth(shown)+20),height=28;
        int halfWidth=preview.width/2,halfHeight=preview.height/2;
        // Keep the label outside the OS drag preview, which can paint above application layers.
        int x=pointer.x+halfWidth+12,y=pointer.y+12;
        if(x+width>surface.getWidth()-6){
            x=pointer.x-halfWidth-12-width;
            if(x<6){
                x=pointer.x+12;y=pointer.y+halfHeight+12;
                if(y+height>surface.getHeight()-6)y=pointer.y-halfHeight-12-height;
            }
        }
        x=Math.max(6,Math.min(x,surface.getWidth()-width-6));
        y=Math.max(6,Math.min(y,surface.getHeight()-height-6));
        Rectangle next=new Rectangle(x,y,Math.max(1,width),height);
        if(bounds.equals(next)&&!changed&&visible())return;
        Rectangle dirty=bounds.isEmpty()?new Rectangle(next):bounds.union(next);bounds=next;repaint(surface,dirty);
    }

    void clear(JComponent surface){
        Rectangle dirty=bounds;bounds=new Rectangle();caption="";shown="";repaint(surface,dirty);
    }

    private static void repaint(JComponent surface,Rectangle dirty){
        dirty=dirty.intersection(new Rectangle(0,0,surface.getWidth(),surface.getHeight()));
        if(!dirty.isEmpty())surface.repaint(dirty.x-2,dirty.y-2,dirty.width+4,dirty.height+5);
    }

    void paint(Graphics2D graphics){
        if(!visible())return;
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
            int x=bounds.x,y=bounds.y,w=bounds.width,h=bounds.height;
            g.setColor(new Color(0,0,0,18));g.fillRoundRect(x,y+2,w,h,12,12);
            g.setColor(new Color(255,255,255,248));g.fillRoundRect(x,y,w,h,12,12);
            g.setColor(new Color(0xd7e1ee));g.drawRoundRect(x,y,w-1,h-1,11,11);
            g.setFont(FONT);g.setColor(new Color(0x263345));FontMetrics fm=g.getFontMetrics();
            g.clipRect(x+10,y+2,Math.max(0,w-20),h-4);
            g.drawString(shown,x+10,y+(h-fm.getHeight())/2+fm.getAscent());
        }finally{g.dispose();}
    }
}
