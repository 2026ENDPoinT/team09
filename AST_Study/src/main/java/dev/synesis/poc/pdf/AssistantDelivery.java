package dev.synesis.poc.pdf;

import java.awt.*;
import javax.swing.*;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

final class AssistantDelivery {
    private static final DateTimeFormatter READ_DATE=DateTimeFormatter.ofPattern("yyyy. M. d.");
    static String label(long receivedAt,long now){
        if(receivedAt<=0)return "전송됨";
        long minutes=Math.max(0,now-receivedAt)/60_000;
        if(minutes==0)return "방금 읽음";
        if(minutes<60)return minutes+"분전 읽음";
        long hours=minutes/60;
        if(hours<23)return hours+"시간 전 읽음";
        return "읽음: "+READ_DATE.format(Instant.ofEpochMilli(receivedAt).atZone(ZoneId.systemDefault()));
    }

    /** Uses the chat's existing animation pulse; retains only the outgoing text. */
    static final class StatusLabel extends JLabel {
        private static final long DURATION=200_000_000L;
        private static final Color SENT=new Color(0xb9c5d5),READ=new Color(0xd5deeb);
        private String outgoing;
        private long started;

        void showStatus(String value){
            if(value.equals(getText()))return;
            boolean transition=isShowing()&&"전송됨".equals(getText())&&!"전송됨".equals(value);
            outgoing=transition?getText():null;
            started=transition?System.nanoTime():0;
            setForeground("방금 읽음".equals(value)?READ:SENT);
            setText(value);
        }

        boolean animating(){return outgoing!=null;}

        void advance(){
            if(outgoing==null)return;
            if(System.nanoTime()-started>=DURATION)outgoing=null;
            repaint();
        }

        @Override protected void paintComponent(Graphics graphics){
            if(outgoing==null){super.paintComponent(graphics);return;}
            float t=Math.min(1f,(System.nanoTime()-started)/(float)DURATION);
            float eased=t*t*(3-2*t);
            Graphics2D g=(Graphics2D)graphics.create();
            try{
                g.setFont(getFont());g.setColor(getForeground());
                g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
                FontMetrics fm=g.getFontMetrics();Insets insets=getInsets();
                int right=getWidth()-insets.right;
                int baseline=insets.top+(getHeight()-insets.top-insets.bottom-fm.getHeight())/2+fm.getAscent();
                // Preserve the bubble's own fade composite instead of replacing it.
                float parentAlpha=g.getComposite() instanceof AlphaComposite c?c.getAlpha():1f;
                g.setComposite(AlphaComposite.SrcOver.derive(parentAlpha*(1-eased)));
                g.setColor("방금 읽음".equals(outgoing)?READ:SENT);
                g.drawString(outgoing,right-fm.stringWidth(outgoing),baseline-2*eased);
                g.setComposite(AlphaComposite.SrcOver.derive(parentAlpha*eased));
                g.setColor(getForeground());
                g.drawString(getText(),right-fm.stringWidth(getText()),baseline+2*(1-eased));
            }finally{g.dispose();}
        }
    }
}
