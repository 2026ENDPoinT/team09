plugins {
    application
    java
}

repositories {
    mavenCentral()
}

val os = System.getProperty("os.name").lowercase()
dependencies {
    implementation("org.apache.pdfbox:pdfbox:3.0.8")
    implementation("com.google.code.gson:gson:2.13.2")
    implementation("org.commonmark:commonmark:0.30.0")
    implementation("org.commonmark:commonmark-ext-gfm-tables:0.30.0")
    implementation("org.scilab.forge:jlatexmath:1.0.7")
}

application {
    mainClass = "dev.synesis.poc.AstStudyMain"
}

tasks.named<JavaExec>("run") {
    jvmArgs("-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8")
    if (os.contains("mac")) jvmArgs("-Xdock:name=AST Study")
}

if (os.contains("mac")) {
    // Native fullscreen completion events let Swing refresh layouts after the title bar disappears.
    tasks.withType<JavaExec>().configureEach {
        jvmArgs("--add-exports=java.desktop/com.apple.eawt=ALL-UNNAMED")
    }
}

java {
    toolchain.languageVersion = JavaLanguageVersion.of(21)
}

tasks.withType<JavaCompile>().configureEach {
    options.encoding = "UTF-8"
}
