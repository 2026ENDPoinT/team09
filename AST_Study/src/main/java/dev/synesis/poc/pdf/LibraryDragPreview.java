package dev.synesis.poc.pdf;

import javax.swing.Icon;
import javax.swing.JComponent;
import java.awt.Component;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.Color;
import java.awt.Font;
import java.awt.image.BufferedImage;
import java.util.List;
import java.util.function.Consumer;

/** A small transparent copy of the displayed artwork, captured only when a drag starts. */
final class LibraryDragPreview {
    private static final int MAX_EDGE=160;

    private LibraryDragPreview() {}

    static BufferedImage icon(Icon icon,Component source) {
        return render(icon.getIconWidth(),icon.getIconHeight(),g->icon.paintIcon(source,g,0,0));
    }

    static BufferedImage capture(JComponent artwork) {
        return render(artwork.getWidth(),artwork.getHeight(),artwork::printAll);
    }

    /** One small cursor image, independent of how many documents the transfer contains. */
    static BufferedImage stack(List<BufferedImage> images,int count) {
        BufferedImage stack=new BufferedImage(MAX_EDGE,MAX_EDGE,BufferedImage.TYPE_INT_ARGB_PRE);
        Graphics2D g=stack.createGraphics();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            for(int i=Math.min(3,images.size())-1;i>=0;i--) {
                BufferedImage image=images.get(i);
                double scale=Math.min(1,138d/Math.max(image.getWidth(),image.getHeight()));
                int w=(int)Math.round(image.getWidth()*scale),h=(int)Math.round(image.getHeight()*scale);
                g.drawImage(image,(MAX_EDGE-w)/2+i*5-5,(MAX_EDGE-h)/2-i*5+5,w,h,null);
            }
            g.setFont(dev.synesis.poc.ui.LibraryDesign.font(Font.BOLD,13));
            String label=String.valueOf(count);int w=Math.max(26,g.getFontMetrics().stringWidth(label)+14);
            g.setColor(new Color(20,20,20));g.fillRoundRect(MAX_EDGE-w-2,MAX_EDGE-28,w,25,25,25);
            g.setColor(Color.WHITE);g.drawString(label,MAX_EDGE-w-2+(w-g.getFontMetrics().stringWidth(label))/2,MAX_EDGE-11);
        } finally {g.dispose();}
        return stack;
    }

    private static BufferedImage render(int width,int height,Consumer<Graphics2D> paint) {
        width=Math.max(1,width);height=Math.max(1,height);
        double scale=Math.min(1,MAX_EDGE/(double)Math.max(width,height));
        BufferedImage image=new BufferedImage(Math.max(1,(int)Math.ceil(width*scale)),
            Math.max(1,(int)Math.ceil(height*scale)),BufferedImage.TYPE_INT_ARGB_PRE);
        Graphics2D graphics=image.createGraphics();
        try {
            graphics.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            graphics.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            graphics.scale(scale,scale);
            paint.accept(graphics);
        } finally {graphics.dispose();}
        return image;
    }
}
