<!DOCTYPE html>
<html>
<head>
    <meta charset="<?php bloginfo('charset'); ?>">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
    <div class="container">
        <h1>🚀 SOURCE WORDPRESS</h1>
        <div class="badge">This is the Original Instance</div>
        <p style="margin-top: 30px; font-size: 1.1em;">
            <?php bloginfo('description'); ?>
        </p>
    </div>
    <?php wp_footer(); ?>
</body>
</html>
