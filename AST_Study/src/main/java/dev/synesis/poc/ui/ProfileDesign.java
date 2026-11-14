package dev.synesis.poc.ui;

import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.border.EmptyBorder;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

/** Figma 94:366. Account presentation only; unavailable actions have no side effects. */
public final class ProfileDesign {
    private static final Color INK=LibraryDesign.INK, MUTED=LibraryDesign.MUTED, SECONDARY=new Color(0x555555);
    private static final Map<String,BufferedImage> ICONS=new HashMap<>();
    private ProfileDesign() {}

    private static JLabel text(String value,int size,boolean bold,Color color) {
        JLabel label=new JLabel(value);label.setFont(LibraryDesign.font(bold?Font.BOLD:Font.PLAIN,size));label.setForeground(color);return label;
    }
    private static Icon icon(String name,int width,int height) {
        BufferedImage source=ICONS.computeIfAbsent(name,key->{
            try(var in=ProfileDesign.class.getResourceAsStream("/dev/synesis/poc/profile/"+key+".png")) {
                if(in==null)throw new IllegalStateException("Missing profile icon: "+key);
                return ImageIO.read(in);
            }catch(IOException error){throw new IllegalStateException(error);}
        });
        return new Icon(){public int getIconWidth(){return width;}public int getIconHeight(){return height;}
            public void paintIcon(Component c,Graphics g,int x,int y){Graphics2D copy=(Graphics2D)g.create();try{copy.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BICUBIC);copy.drawImage(source,x,y,width,height,null);}finally{copy.dispose();}}};
    }
    private static JPanel transparent(LayoutManager layout){JPanel p=new JPanel(layout);p.setOpaque(false);return p;}
    private static void keepButtonText(JButton button) {
        button.setUI(new javax.swing.plaf.basic.BasicButtonUI() {
            @Override public void paint(Graphics g,JComponent c) {
                if(button.getBorder()!=null)button.getBorder().paintBorder(button,g,0,0,button.getWidth(),button.getHeight());
                super.paint(g,c);
            }
            @Override protected void paintText(Graphics g,JComponent c,Rectangle rect,String value) {
                g.setColor(button.getForeground());
                javax.swing.plaf.basic.BasicGraphicsUtils.drawStringUnderlineCharAt(g,value,-1,rect.x,rect.y+g.getFontMetrics().getAscent());
            }
        });
    }
    private static JButton button(String title,int width,int height,boolean primary,boolean available){
        JButton b=new JButton(title);LibraryDesign.button(b,primary);b.setFont(LibraryDesign.medium(12));b.setPreferredSize(new Dimension(width,height));keepButtonText(b);
        if(!available){b.setEnabled(false);b.setToolTipText("준비 중이에요");b.putClientProperty("synesis.placeholder",Boolean.TRUE);b.setDisabledIcon(b.getIcon());}
        return b;
    }
    private static JButton placeholder(String title,int width,int height){return button(title,width,height,false,false);}
    private static class Card extends JPanel {
        Card(){super(null);setOpaque(false);}
        @Override protected void paintComponent(Graphics graphics){Graphics2D g=(Graphics2D)graphics.create();try{
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            for(int spread=3;spread>0;spread--){g.setColor(new Color(0,0,0,2));g.fillRoundRect(3-spread,4-spread,getWidth()-6+spread*2,getHeight()-7+spread*2,24,24);}
            g.setColor(Color.WHITE);g.fillRoundRect(1,1,getWidth()-3,getHeight()-4,24,24);
            g.setColor(new Color(0xe2e7ed));g.drawRoundRect(1,1,getWidth()-3,getHeight()-4,24,24);
        }finally{g.dispose();}}
    }
    private static JComponent line(){JPanel p=new JPanel();p.setBackground(LibraryDesign.LINE);return p;}
    private static JLabel heading(String title,String glyph){JLabel l=text(title,18,true,INK);if(glyph!=null){l.setIcon(icon(glyph,18,18));l.setIconTextGap(8);}return l;}
    private static JPanel securityRow(String title,String description,String action){
        JPanel p=new JPanel(null){{setOpaque(false);}@Override public void doLayout(){getComponent(0).setBounds(0,0,Math.max(0,getWidth()-80),20);getComponent(1).setBounds(0,20,Math.max(0,getWidth()-80),18);getComponent(2).setBounds(getWidth()-64,5,64,30);}};
        p.add(text(title,13,false,INK));p.add(text(description,12,false,MUTED));p.add(placeholder(action,64,30));return p;
    }
    private static Card card(java.util.function.Consumer<Card> layout){return new Card(){@Override public void doLayout(){layout.accept(this);}};}
    private static void bounds(Container p,int child,int x,int y,int w,int h){p.getComponent(child).setBounds(x,y,Math.max(0,w),h);}
    private static JButton link(String title,boolean available){JButton b=button(title,100,32,false,available);b.setBorder(new EmptyBorder(0,0,0,0));b.setBorderPainted(false);b.setContentAreaFilled(false);b.setHorizontalAlignment(SwingConstants.LEFT);b.setForeground(MUTED);return b;}

    public static JComponent create(JLabel plan,JLabel nextBilling,JLabel balance,JLabel planState,
                                    JProgressBar creditProgress,JLabel creditSummary,JButton topUp,
                                    JButton usage,JButton logout) {
        Card identity=card(p->{int w=p.getWidth();bounds(p,0,24,29,64,64);bounds(p,1,104,25,w-250,30);bounds(p,2,104,55,w-250,20);bounds(p,3,104,75,w-250,18);bounds(p,4,w-128,44,104,34);bounds(p,5,24,114,w-48,1);bounds(p,6,24,132,Math.min(300,(w-48)/2),28);bounds(p,7,24+Math.min(332,(w-48)/2),132,Math.max(0,w-380),28);});
        JLabel avatar=text("M",26,true,INK);avatar.setHorizontalAlignment(SwingConstants.CENTER);
        JPanel avatarCircle=new JPanel(new GridBagLayout()){@Override protected void paintComponent(Graphics g){Graphics2D c=(Graphics2D)g.create();c.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);c.setColor(new Color(0xf5f8fc));c.fillOval(0,0,64,64);c.dispose();}};avatarCircle.setOpaque(false);avatarCircle.add(avatar);
        identity.add(avatarCircle);identity.add(text("김민준",22,true,INK));identity.add(text("내 배움을 쌓아가는 개인 워크스페이스",13,false,SECONDARY));identity.add(text("개인 계정",11,false,MUTED));identity.add(placeholder("프로필 수정",104,34));identity.add(line());identity.add(text("계정 유형   개인 계정",12,false,SECONDARY));identity.add(text("학습 언어   한국어",12,false,SECONDARY));

        Card security=card(p->{int w=p.getWidth()-48;bounds(p,0,24,24,w,30);bounds(p,1,24,66,w,44);bounds(p,2,24,110,w,1);bounds(p,3,24,111,w,44);bounds(p,4,24,155,w,1);bounds(p,5,24,156,w,44);});
        security.add(heading("계정 · 보안","shield"));security.add(securityRow("이메일","이메일 주소를 등록해 주세요.","등록"));security.add(line());security.add(securityRow("비밀번호","비밀번호를 변경하고 계정을 안전하게 보호해요.","변경"));security.add(line());security.add(securityRow("로그인 기기","접속 중인 기기를 확인하고 관리해요.","관리"));

        Card learning=card(p->{int w=p.getWidth();bounds(p,0,20,20,w-40,28);bounds(p,1,20,58,w-40,32);bounds(p,2,20,98,w-40,32);});
        learning.add(heading("학습 환경",null));
        JPanel notifications=new JPanel(new BorderLayout(8,0));notifications.setOpaque(false);JLabel bell=text("학습 알림",13,false,SECONDARY);bell.setIcon(icon("bell",16,16));bell.setIconTextGap(8);notifications.add(bell,BorderLayout.WEST);
        JLabel toggle=text("켜짐",12,false,MUTED);toggle.setIcon(icon("notifications-on",40,22));toggle.setHorizontalTextPosition(SwingConstants.LEFT);toggle.setIconTextGap(8);toggle.setToolTipText("알림 설정은 준비 중이에요");notifications.add(toggle,BorderLayout.EAST);learning.add(notifications);
        JPanel export=transparent(new BorderLayout());JLabel download=text("내 학습 데이터",13,false,SECONDARY);download.setIcon(icon("download",16,16));download.setIconTextGap(8);export.add(download,BorderLayout.WEST);export.add(placeholder("다운로드",96,32),BorderLayout.EAST);learning.add(export);

        Card subscription=card(p->{int w=p.getWidth();bounds(p,0,20,20,w-100,16);bounds(p,1,20,36,w-100,32);bounds(p,2,w-80,32,60,24);bounds(p,3,20,76,w-40,20);bounds(p,4,20,104,w-40,20);bounds(p,5,20,136,w-40,36);});
        subscription.add(text("현재 플랜",11,false,MUTED));plan.setFont(LibraryDesign.font(Font.BOLD,24));plan.setForeground(INK);subscription.add(plan);
        planState.setFont(LibraryDesign.font(Font.PLAIN,11));planState.setHorizontalAlignment(SwingConstants.CENTER);planState.setOpaque(true);planState.setBackground(new Color(0xf5f8fc));planState.setForeground(SECONDARY);subscription.add(planState);
        subscription.add(text("자료 정리부터 AI멘토까지, 꾸준한 학습을 위해.",12,false,SECONDARY));nextBilling.setFont(LibraryDesign.font(Font.PLAIN,12));nextBilling.setForeground(MUTED);subscription.add(nextBilling);subscription.add(placeholder("구독·결제 관리",422,36));

        Card credits=card(p->{int w=p.getWidth();bounds(p,0,20,20,w-122,32);bounds(p,1,w-102,20,82,34);bounds(p,2,20,60,w-40,44);bounds(p,3,20,112,w-40,6);bounds(p,4,20,126,w-40,18);bounds(p,5,20,156,w-40,24);});
        credits.add(heading("크레딧","wallet"));LibraryDesign.button(topUp,true);topUp.setFont(LibraryDesign.medium(12));keepButtonText(topUp);credits.add(topUp);
        balance.setFont(LibraryDesign.font(Font.BOLD,30));balance.setForeground(INK);
        JPanel balanceRow=transparent(new FlowLayout(FlowLayout.LEFT,0,0));balanceRow.add(balance);
        balanceRow.add(Box.createHorizontalStrut(8));balanceRow.add(text("남은 크레딧",12,false,MUTED));credits.add(balanceRow);
        creditProgress.setBorderPainted(false);creditProgress.setOpaque(false);creditProgress.setUI(new javax.swing.plaf.basic.BasicProgressBarUI(){@Override public void paint(Graphics g,JComponent c){Graphics2D copy=(Graphics2D)g.create();copy.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);copy.setColor(new Color(0xf5f8fc));copy.fillRoundRect(0,0,c.getWidth(),6,6,6);copy.setColor(INK);copy.fillRoundRect(0,0,(int)Math.round(c.getWidth()*creditProgress.getPercentComplete()),6,6,6);copy.dispose();}});credits.add(creditProgress);
        creditSummary.setFont(LibraryDesign.font(Font.PLAIN,11));creditSummary.setForeground(MUTED);credits.add(creditSummary);
        LibraryDesign.button(usage,false);usage.setBorder(new EmptyBorder(0,0,0,0));usage.setBorderPainted(false);usage.setContentAreaFilled(false);usage.setHorizontalAlignment(SwingConstants.LEFT);usage.setFont(LibraryDesign.medium(12));usage.setIcon(icon("arrow",16,16));usage.setHorizontalTextPosition(SwingConstants.LEFT);usage.setIconTextGap(12);credits.add(usage);

        Card help=card(p->{int w=p.getWidth()-40;bounds(p,0,20,20,w,28);bounds(p,1,20,60,w,36);bounds(p,2,20,104,w,36);});help.add(heading("도움말 · 문의",null));
        for(String[] entry:new String[][]{{"사용 가이드","book"},{"문의하기","help"}}){JPanel row=transparent(new BorderLayout(8,0));JLabel label=text(entry[0],13,false,SECONDARY);label.setIcon(icon(entry[1],16,16));label.setIconTextGap(8);row.add(label,BorderLayout.WEST);JLabel arrow=new JLabel(icon("next",14,14));row.add(arrow,BorderLayout.EAST);row.setToolTipText("준비 중이에요");help.add(row);}

        JPanel footer=new JPanel(null){@Override public void doLayout(){ProfileDesign.bounds(this,0,0,2,112,32);ProfileDesign.bounds(this,1,112,2,80,32);ProfileDesign.bounds(this,2,getWidth()-204,2,88,32);ProfileDesign.bounds(this,3,getWidth()-88,2,88,32);}};footer.setOpaque(false);
        footer.add(link("개인정보 처리방침",false));footer.add(link("이용약관",false));footer.add(link("계정 탈퇴",false));LibraryDesign.button(logout,false);logout.setBorder(new EmptyBorder(0,0,0,0));logout.setContentAreaFilled(false);logout.setBorderPainted(false);logout.setFont(LibraryDesign.medium(12));logout.setIcon(icon("logout",14,14));footer.add(logout);
        return new Surface(identity,security,learning,subscription,credits,help,footer);
    }

    private static final class Surface extends JPanel implements Scrollable {
        Surface(JComponent... children){super(null);setBackground(Color.WHITE);add(text("내 정보",32,true,INK));add(text("계정과 구독, 학습 환경을 한곳에서 관리해요.",14,false,MUTED));for(JComponent child:children)add(child);}
        private boolean stacked(){return getWidth()>0&&getWidth()<960;}
        @Override public Dimension getPreferredSize(){return new Dimension(1100,stacked()?1500:806);}
        @Override public void doLayout(){int w=getWidth(),inner=Math.max(0,w-72);ProfileDesign.bounds(this,0,36,28,inner,44);ProfileDesign.bounds(this,1,36,76,inner,22);int left=stacked()?inner:(int)Math.round((inner-20)*876.0/1338),right=inner-left-20,rx=36+left+20,ry=124;if(stacked()){right=inner;rx=36;ry=754;}ProfileDesign.bounds(this,2,36,124,left,196);ProfileDesign.bounds(this,3,36,336,left,234);ProfileDesign.bounds(this,4,36,586,left,152);ProfileDesign.bounds(this,5,rx,ry,right,196);ProfileDesign.bounds(this,6,rx,ry+212,right,218);ProfileDesign.bounds(this,7,rx,ry+446,right,168);ProfileDesign.bounds(this,8,36,stacked()?1388:758,inner,36);}
        public Dimension getPreferredScrollableViewportSize(){return new Dimension(1100,806);}
        public int getScrollableUnitIncrement(Rectangle r,int orientation,int direction){return 24;}
        public int getScrollableBlockIncrement(Rectangle r,int orientation,int direction){return Math.max(24,r.height-24);}
        public boolean getScrollableTracksViewportWidth(){return true;}
        public boolean getScrollableTracksViewportHeight(){return false;}
    }
}
