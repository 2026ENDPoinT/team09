package dev.synesis.poc.ui;

import javax.swing.*;
import javax.swing.border.EmptyBorder;
import java.awt.*;
import java.awt.event.*;
import java.awt.geom.RoundRectangle2D;
import java.awt.image.BufferedImage;
import java.awt.image.ConvolveOp;
import java.awt.image.Kernel;

/** Scoped glass-pane presentation of Figma Make's four-plan comparison. No wallet mutation. */
public final class LibraryPlanPrompt extends JPanel {
    private static final Color INK=new Color(0x151515),MUTED=new Color(0x777777);
    private static final String[] NAMES={"Free","Standard","Pro","Extra Pro"};
    private static final String[] PRICES={"0","9,900","19,900","29,900"};
    private static final String[] CREDITS={"100","2,500","6,000","10,000"};
    private static final String[] KICKERS={"부담 없이 시작하는 플랜","집중 학습을 위한 플랜","더 많은 학습을 위한 플랜","한계 없이 몰입하는 플랜"};
    private static final String[] FEATURES={"PDF 업로드 및 분석","개념·이해·실전 N제 출제","SYNOTE 무제한 이용","플래너 무료 이용","학점관리 서비스 무제한 이용","수식 그래프 검증 툴","Premium 학습 에이전트","일정 자동화","에타 시간표 연동","SYNESIS local MCP","모든 광고 제거"};
    private final JRootPane root;
    private final Component previousGlass,previousFocus;
    private final boolean previousVisible;
    private final Runnable closed;
    private final JPanel surface,plans;
    private final JScrollPane scroll;
    private final JButton exit;
    private Timer animation;
    private final BufferedImage backdrop,dimmedBackdrop;
    private BufferedImage motionImage;
    private float opacity;
    private float closingFrom;
    private long started;
    private boolean closing;
    public static void open(Component parent,Runnable closed){
        JRootPane root=SwingUtilities.getRootPane(parent);
        if(root==null){closed.run();return;}
        if(root.getGlassPane() instanceof LibraryPlanPrompt){closed.run();return;}
        LibraryPlanPrompt prompt=new LibraryPlanPrompt(root,closed);root.setGlassPane(prompt);
        prompt.setSize(root.getSize());layoutTree(prompt);prompt.snapshotSurface();
        prompt.setVisible(true);prompt.exit.requestFocusInWindow();
        // Start the clock after expensive construction, layout and the single snapshot.
        prompt.started=System.nanoTime();prompt.animation.start();
    }
    private LibraryPlanPrompt(JRootPane root,Runnable closed){
        this.root=root;this.closed=closed;previousGlass=root.getGlassPane();previousVisible=previousGlass.isVisible();previousFocus=KeyboardFocusManager.getCurrentKeyboardFocusManager().getFocusOwner();
        setOpaque(true);setLayout(null);setFocusCycleRoot(true);
        backdrop=capture(root);
        dimmedBackdrop=dim(backdrop);
        surface=new JPanel(new BorderLayout()){
            @Override protected void paintComponent(Graphics gg){Graphics2D g=(Graphics2D)gg.create();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setColor(Color.WHITE);g.fillRoundRect(0,0,getWidth(),getHeight(),36,36);g.dispose();}
            @Override protected void paintChildren(Graphics gg){Graphics2D g=(Graphics2D)gg.create();g.clip(new RoundRectangle2D.Double(0,0,getWidth(),getHeight(),36,36));super.paintChildren(g);g.dispose();}};
        surface.setOpaque(false);surface.setBorder(new EmptyBorder(28,0,20,0));
        JPanel contents=column();contents.setBorder(new EmptyBorder(12,38,0,38));
        try(var in=LibraryPlanPrompt.class.getResourceAsStream("/dev/synesis/poc/advertising/synesis-mark.png")){
            BufferedImage logo=javax.imageio.ImageIO.read(in);
            JLabel mark=new JLabel(new DeviceImageIcon(logo,68,70));mark.setAlignmentX(.5f);
            contents.add(mark);contents.add(Box.createVerticalStrut(12));
        }catch(java.io.IOException error){throw new IllegalStateException("Cannot read SYNESIS plan mark",error);}
        JLabel brand=label("SYNESIS PLANS",9,Font.BOLD,MUTED);brand.setAlignmentX(.5f);contents.add(brand);contents.add(Box.createVerticalStrut(6));
        JLabel title=label("내 학습 방식에 맞는 플랜을 선택하세요",22,Font.BOLD,INK);title.setAlignmentX(.5f);contents.add(title);contents.add(Box.createVerticalStrut(7));
        JLabel subtitle=label("처음 가입하면 모든 사용자에게 30일 무료 이용 기간을 제공해요.",11,Font.PLAIN,MUTED);subtitle.setAlignmentX(.5f);contents.add(subtitle);contents.add(Box.createVerticalStrut(26));
        plans=new JPanel(new GridLayout(1,4,12,12));plans.setOpaque(false);plans.setAlignmentX(.5f);
        for(int i=0;i<4;i++)plans.add(card(i));contents.add(plans);
        JButton later=button("다음에 할게요",false);later.setUI(new javax.swing.plaf.basic.BasicButtonUI());later.setBorder(null);later.setForeground(new Color(0x888888));later.setAlignmentX(.5f);later.addActionListener(e->dismiss());
        contents.add(Box.createVerticalStrut(17));contents.add(later);
        scroll=new dev.synesis.poc.ui.UnifiedScrollPane(contents);scroll.setBorder(null);scroll.setOpaque(false);scroll.getViewport().setOpaque(false);scroll.getVerticalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
        scroll.getVerticalScrollBar().setUI(new FadingScrollBarUI(Color.BLACK,.18f));
        scroll.getVerticalScrollBar().setPreferredSize(new Dimension(7,0));surface.add(scroll);
        exit=new JButton("×");exit.setFont(LibraryDesign.font(Font.PLAIN,22));exit.setForeground(MUTED);exit.setBorder(null);exit.setOpaque(false);exit.setContentAreaFilled(false);exit.getAccessibleContext().setAccessibleName("프리미엄 안내 닫기");exit.addActionListener(e->dismiss());
        add(exit);add(surface);
        addMouseListener(new MouseAdapter(){public void mousePressed(MouseEvent e){if(!surface.getBounds().contains(e.getPoint()))dismiss();}});
        addMouseWheelListener(e->e.consume());
        getInputMap(WHEN_ANCESTOR_OF_FOCUSED_COMPONENT).put(KeyStroke.getKeyStroke(KeyEvent.VK_ESCAPE,0),"close");getActionMap().put("close",new AbstractAction(){public void actionPerformed(ActionEvent e){dismiss();}});
        animation=new Timer(16,e->{
            float elapsed=(System.nanoTime()-started)/1_000_000f;
            float t=Math.min(1,elapsed/(closing?160:240));
            float eased=1-(1-t)*(1-t)*(1-t);
            opacity=closing?closingFrom*(1-eased):eased;
            if(t>=1){animation.stop();motionImage=null;if(closing){restore();return;}}
            repaint();
        });
        animation.setCoalesce(true);
    }
    private JPanel card(int index){
        boolean free=index==0,recommended=index==1;
        JPanel p=new JPanel(new BorderLayout(0,18)){
            @Override protected void paintComponent(Graphics gg){Graphics2D g=(Graphics2D)gg.create();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setColor(recommended?Color.WHITE:new Color(0xfafaf9));g.fillRoundRect(0,0,getWidth()-1,getHeight()-1,28,28);g.setColor(new Color(recommended?0x242424:0xe1e1df));g.drawRoundRect(0,0,getWidth()-1,getHeight()-1,28,28);g.dispose();}};
        p.setOpaque(false);p.setBorder(new EmptyBorder(20,18,20,18));
        JPanel top=column();
        JLabel badge=label(recommended?"RECOMMENDED":free?"최초 가입 30일 제공":" ",7,Font.BOLD,recommended?Color.WHITE:MUTED);
        if(recommended){badge.setOpaque(true);badge.setBackground(INK);badge.setBorder(new EmptyBorder(4,8,4,8));}badge.setAlignmentX(0);badge.setPreferredSize(new Dimension(140,17));badge.setMaximumSize(new Dimension(180,17));top.add(badge);top.add(Box.createVerticalStrut(9));
        top.add(label(KICKERS[index],9,Font.PLAIN,new Color(0x8a8a8a)));top.add(label(NAMES[index],21,Font.BOLD,INK));top.add(Box.createVerticalStrut(14));
        top.add(label("<html><b>"+PRICES[index]+"원</b><span style='font-size:7px;color:#999999'> / 월</span></html>",18,Font.BOLD,INK));top.add(Box.createVerticalStrut(10));
        JPanel credit=new JPanel(){@Override protected void paintComponent(Graphics gg){
            Graphics2D g=(Graphics2D)gg.create();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            g.setColor(free?new Color(0xeeeeeb):new Color(0x181818));g.fillRoundRect(0,0,getWidth(),getHeight(),18,18);
            g.setColor(free?INK:Color.WHITE);g.setFont(LibraryDesign.font(Font.BOLD,22));g.drawString(CREDITS[index],13,36);int end=13+g.getFontMetrics().stringWidth(CREDITS[index]);
            g.setColor(new Color(0x999999));g.setFont(LibraryDesign.font(Font.BOLD,11));g.drawString(".00",end+1,36);end+=g.getFontMetrics().stringWidth(".00")+11;
            g.setFont(LibraryDesign.font(Font.PLAIN,8));g.drawString((free?"무료":"유료")+" 크레딧",end,25);g.drawString("매달 제공",end,38);g.dispose();}};
        credit.setOpaque(false);credit.setAlignmentX(0);credit.setPreferredSize(new Dimension(220,58));credit.setMaximumSize(new Dimension(Integer.MAX_VALUE,58));top.add(credit);top.add(Box.createVerticalStrut(18));
        top.add(feature("매달 "+(free?"무료":"유료")+" 크레딧 "+CREDITS[index]+"개",true,null,false));
        for(int i=0;i<FEATURES.length;i++){
            boolean available=!free||i<5;String info=null;
            if(i==6)info="<html><b>나만의 학습 전략을 만드는 AI 에이전트</b><br>학습 자료를 연결해 취약 개념을 찾고,<br>맞춤 복습 순서와 문제를 제안해요.</html>";
            if(free&&i==1)info="<html><b>내 자료로 만드는 맞춤형 N제</b><br>개념 확인, 심화 이해, 실전 문제까지<br>난이도를 조절해 원하는 만큼 출제해요.</html>";
            top.add(feature(FEATURES[i],available,info,i<2));
        }
        p.add(top,BorderLayout.CENTER);
        JButton choose=button(free?"Free 계속 사용":NAMES[index]+" 선택  ›",!free);choose.setFont(LibraryDesign.font(Font.BOLD,11));choose.setPreferredSize(new Dimension(160,40));
        choose.addActionListener(e->{if(free)dismiss();else JOptionPane.showMessageDialog(this,NAMES[index]+" 플랜을 선택했어요.\n구독 결제는 아직 연결되지 않았어요.","SYNESIS PLANS",JOptionPane.INFORMATION_MESSAGE);});
        p.add(choose,BorderLayout.SOUTH);return p;
    }
    private static JPanel feature(String text,boolean available,String info,boolean usage){
        JPanel row=new JPanel(new BorderLayout(7,0));row.setOpaque(false);row.setAlignmentX(0);row.setBorder(new EmptyBorder(0,0,8,0));
        JLabel status=new JLabel(available?"✓":"×",SwingConstants.CENTER){@Override protected void paintComponent(Graphics gg){Graphics2D g=(Graphics2D)gg.create();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setColor(new Color(available?0xe9e9e6:0xf0f0ee));g.fillOval(0,(getHeight()-18)/2,18,18);g.dispose();super.paintComponent(gg);}};
        status.setPreferredSize(new Dimension(18,18));status.setFont(LibraryDesign.font(Font.PLAIN,12));status.setForeground(available?INK:new Color(0xaaaaaa));row.add(status,BorderLayout.WEST);
        row.add(label("<html>"+text+(usage?" <span style='color:#888888;font-size:7px'>크레딧 소모</span>":"")+"</html>",10,Font.PLAIN,available?new Color(0x363636):new Color(0xaaaaaa)),BorderLayout.CENTER);
        if(info!=null){JButton more=button("*",true);more.setMargin(new Insets(0,0,0,0));more.setUI(new javax.swing.plaf.basic.BasicButtonUI());more.setBorder(null);more.setOpaque(true);more.setPreferredSize(new Dimension(18,18));more.setToolTipText(info);more.getAccessibleContext().setAccessibleName(text+" 기능 설명");more.addActionListener(e->JOptionPane.showMessageDialog(row,info,text,JOptionPane.PLAIN_MESSAGE));row.add(more,BorderLayout.EAST);}return row;
    }
    private static JPanel column(){JPanel p=new JPanel();p.setOpaque(false);p.setLayout(new BoxLayout(p,BoxLayout.Y_AXIS));return p;}
    private static JLabel label(String text,int size,int style,Color color){JLabel l=new JLabel(text);l.setFont(LibraryDesign.font(style,size));l.setForeground(color);l.setAlignmentX(0);return l;}
    private static JButton button(String text,boolean dark){JButton b=new JButton(text);LibraryDesign.button(b,dark);return b;}
    private static BufferedImage capture(JRootPane root){
        double scale=Math.min(1,Math.sqrt(1_600_000d/(Math.max(1d,root.getWidth())*Math.max(1,root.getHeight()))));
        int w=Math.max(1,(int)(root.getWidth()*scale)),h=Math.max(1,(int)(root.getHeight()*scale));
        BufferedImage image=new BufferedImage(w,h,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();
        g.scale((double)w/Math.max(1,root.getWidth()),(double)h/Math.max(1,root.getHeight()));root.paint(g);g.dispose();return image;
    }
    private static BufferedImage dim(BufferedImage source){
        BufferedImage small=new BufferedImage(Math.max(1,source.getWidth()/3),Math.max(1,source.getHeight()/3),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=small.createGraphics();g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);g.drawImage(source,0,0,small.getWidth(),small.getHeight(),null);g.dispose();
        float[] weights=new float[25];java.util.Arrays.fill(weights,1/25f);
        BufferedImage blurred=new ConvolveOp(new Kernel(5,5,weights),ConvolveOp.EDGE_NO_OP,null).filter(small,null);
        BufferedImage result=new BufferedImage(source.getWidth(),source.getHeight(),BufferedImage.TYPE_INT_RGB);
        g=result.createGraphics();g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        g.drawImage(blurred,0,0,result.getWidth(),result.getHeight(),null);g.setColor(new Color(8,8,8,148));g.fillRect(0,0,result.getWidth(),result.getHeight());g.dispose();return result;
    }
    private static void layoutTree(Container container){container.doLayout();for(Component child:container.getComponents())if(child instanceof Container c)layoutTree(c);}
    private void snapshotSurface(){
        // Bounded transient texture: HTML labels and plan cards paint once, never per frame.
        double scale=Math.min(1.5,Math.sqrt(1_800_000d/(Math.max(1d,surface.getWidth())*Math.max(1,surface.getHeight()))));
        int w=Math.max(1,(int)Math.ceil(surface.getWidth()*scale)),h=Math.max(1,(int)Math.ceil(surface.getHeight()*scale));
        motionImage=new BufferedImage(w,h,BufferedImage.TYPE_INT_ARGB_PRE);
        Graphics2D g=motionImage.createGraphics();g.scale((double)w/surface.getWidth(),(double)h/surface.getHeight());surface.printAll(g);
        g.translate(exit.getX()-surface.getX(),exit.getY()-surface.getY());exit.printAll(g);g.dispose();
    }
    @Override public void doLayout(){
        int width=Math.max(220,Math.min(1440,getWidth()-40)),height=Math.max(150,Math.min(getHeight()-40,940));
        int cols=width>1100?4:width>700?2:1;
        if(((GridLayout)plans.getLayout()).getColumns()!=cols){plans.setLayout(new GridLayout(0,cols,12,12));plans.revalidate();}
        surface.setBounds((getWidth()-width)/2,(getHeight()-height)/2,width,height);exit.setBounds(surface.getX()+width-48,surface.getY()+10,34,34);
    }
    @Override protected void paintComponent(Graphics gg){
        Graphics2D g=(Graphics2D)gg.create();g.drawImage(backdrop,0,0,getWidth(),getHeight(),null);
        g.setComposite(AlphaComposite.SrcOver.derive(opacity));g.drawImage(dimmedBackdrop,0,0,getWidth(),getHeight(),null);g.dispose();
    }
    @Override protected void paintChildren(Graphics gg){
        if(motionImage==null){super.paintChildren(gg);return;}
        Graphics2D g=(Graphics2D)gg.create();g.setComposite(AlphaComposite.SrcOver.derive(opacity));
        double s=.97+.03*opacity;
        int width=(int)Math.round(surface.getWidth()*s),height=(int)Math.round(surface.getHeight()*s);
        int x=surface.getX()+(surface.getWidth()-width)/2,y=surface.getY()+(surface.getHeight()-height)/2+(int)Math.round(14*(1-opacity));
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        g.drawImage(motionImage,x,y,width,height,null);g.dispose();
    }
    private void dismiss(){if(closing)return;if(motionImage==null)snapshotSurface();closingFrom=opacity;closing=true;started=System.nanoTime();animation.restart();}
    private void restore(){animation.stop();setVisible(false);if(root.getGlassPane()==this){root.setGlassPane(previousGlass);previousGlass.setVisible(previousVisible);}if(previousFocus!=null)previousFocus.requestFocusInWindow();closed.run();}
}
